"""Tests for H3 dual incident metrics."""

import tempfile
from pathlib import Path

import duckdb
import pytest


class TestH3DualMetrics:
    """Test dual incident metrics (incidents_unique vs incidents_coverage)."""

    @pytest.fixture
    def test_incidents_file(self, tmp_path: Path) -> Path:
        """Create test incidents with known H3 cells."""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3; LOAD h3")
        conn.execute("SET memory_limit = '100MB'")

        output = tmp_path / "test_incidents.parquet"

        # Create test incidents
        # Incident 1: Crosses 3 H3 cells at res 5
        # Incident 2: Crosses 2 H3 cells at res 5, one overlapping with incident 1
        conn.execute(f"""
            COPY (
                SELECT
                    'inc1' as incident_id,
                    'seg1' as segment_id,
                    'abc123' as icao24,
                    1700000000 as start_time,
                    1700000900 as end_time,
                    900 as duration_seconds,
                    '7700' as squawk_code,
                    75 as confidence_score,
                    'high' as confidence_category,
                    -- Points that will cross multiple H3 cells
                    [
                        {{'time': 1700000000, 'lat': 51.5074, 'lon': -0.1278}},
                        {{'time': 1700000300, 'lat': 51.5174, 'lon': -0.1178}},
                        {{'time': 1700000600, 'lat': 51.5274, 'lon': -0.1078}},
                        {{'time': 1700000900, 'lat': 51.5374, 'lon': -0.0978}}
                    ] as points
                UNION ALL
                SELECT
                    'inc2' as incident_id,
                    'seg2' as segment_id,
                    'def456' as icao24,
                    1700001000 as start_time,
                    1700001600 as end_time,
                    600 as duration_seconds,
                    '7600' as squawk_code,
                    60 as confidence_score,
                    'medium' as confidence_category,
                    -- Points that partially overlap with incident 1
                    [
                        {{'time': 1700001000, 'lat': 51.5274, 'lon': -0.1078}},
                        {{'time': 1700001300, 'lat': 51.5374, 'lon': -0.0978}},
                        {{'time': 1700001600, 'lat': 51.5474, 'lon': -0.0878}}
                    ] as points
            ) TO '{output}' (FORMAT PARQUET)
        """)

        conn.close()
        return output

    @pytest.fixture
    def test_segments_file(self, tmp_path: Path) -> Path:
        """Create test segments for coverage calculations."""
        conn = duckdb.connect(":memory:")
        conn.execute("SET memory_limit = '100MB'")

        output = tmp_path / "test_segments_coverage.parquet"

        # Create segments that pass through same cells
        conn.execute(f"""
            COPY (
                -- 5 segments passing through same area
                SELECT
                    'seg' || CAST(n AS VARCHAR) as segment_id,
                    'plane' || CAST(n AS VARCHAR) as icao24,
                    1700000000 + CAST(n * 1000 AS BIGINT) as start_time,
                    1700000600 + CAST(n * 1000 AS BIGINT) as end_time,
                    600 as duration_seconds,
                    3 as point_count,
                    [
                        {{'time': 1700000000 + CAST(n * 1000 AS BIGINT), 'lat': 51.5074 + CAST(n * 0.001 AS DOUBLE), 'lon': -0.1278, 'squawk': NULL, 'onground': false, 'alert': false, 'callsign': 'TEST' || CAST(n AS VARCHAR)}},
                        {{'time': 1700000300 + CAST(n * 1000 AS BIGINT), 'lat': 51.5174 + CAST(n * 0.001 AS DOUBLE), 'lon': -0.1178, 'squawk': NULL, 'onground': false, 'alert': false, 'callsign': 'TEST' || CAST(n AS VARCHAR)}},
                        {{'time': 1700000600 + CAST(n * 1000 AS BIGINT), 'lat': 51.5274 + CAST(n * 0.001 AS DOUBLE), 'lon': -0.1078, 'squawk': NULL, 'onground': false, 'alert': false, 'callsign': 'TEST' || CAST(n AS VARCHAR)}}
                    ] as points
                FROM generate_series(1, 5) t(n)
            ) TO '{output}' (FORMAT PARQUET)
        """)

        conn.close()
        return output

    def test_dual_incident_metrics(
        self, test_incidents_file: Path, test_segments_file: Path, duckdb_conn: duckdb.DuckDBPyConnection
    ) -> None:
        """Test computation of dual incident metrics."""
        from aviation_anomaly.h3_aggregation import compute_dual_incident_metrics

        output_file = Path(tempfile.gettempdir()) / "h3_dual_metrics.parquet"

        # Compute dual metrics
        compute_dual_incident_metrics(
            incidents_file=test_incidents_file, segments_file=test_segments_file, output_file=output_file, resolution=5
        )

        # Use shared connection for verification
        result = duckdb_conn.execute(f"""
            SELECT
                h3_cell,
                incidents_unique,
                incidents_coverage,
                flights,
                rate_unique_ppm,
                rate_coverage_ppm
            FROM read_parquet('{output_file}')
            WHERE incidents_unique > 0 OR incidents_coverage > 0
            ORDER BY h3_cell
        """).fetchall()

        assert len(result) > 0, "Should have H3 cells with incidents"

        # Check that metrics are computed correctly
        for row in result:
            h3_cell, inc_unique, inc_coverage, flights, rate_unique, rate_coverage = row

            # incidents_unique counts unique incidents per cell (for rate calculation)
            # incidents_coverage counts all incident observations (for heatmap)
            assert inc_coverage >= inc_unique, "Coverage should be >= unique"

            # Rates should be calculated correctly (parts per million)
            if flights > 0:
                expected_rate_unique = (inc_unique / flights) * 1_000_000
                expected_rate_coverage = (inc_coverage / flights) * 1_000_000

                assert abs(rate_unique - expected_rate_unique) < 0.1, "Unique rate calculation"
                assert abs(rate_coverage - expected_rate_coverage) < 0.1, "Coverage rate calculation"

        # Verify overlapping cells have correct counts
        # Cell with 2 incidents should have incidents_unique=2, incidents_coverage may be higher
        cells_with_multiple = [r for r in result if r[1] > 1]  # incidents_unique > 1
        assert len(cells_with_multiple) > 0, "Should have cells with multiple incidents"

    def test_incident_aggregation_by_type(
        self, test_incidents_file: Path, test_segments_file: Path, duckdb_conn: duckdb.DuckDBPyConnection
    ) -> None:
        """Test incident aggregation by squawk type."""
        from aviation_anomaly.h3_aggregation import aggregate_incidents_by_type

        output_file = Path(tempfile.gettempdir()) / "h3_incidents_by_type.parquet"

        # Aggregate by squawk type
        aggregate_incidents_by_type(
            incidents_file=test_incidents_file, segments_file=test_segments_file, output_file=output_file, resolution=5
        )

        # Use shared connection for verification
        result = duckdb_conn.execute(f"""
            SELECT
                h3_cell,
                incidents_7500,
                incidents_7600,
                incidents_7700,
                incidents_all
            FROM read_parquet('{output_file}')
            WHERE incidents_all > 0
        """).fetchall()

        assert len(result) > 0, "Should have aggregated incidents"

        for row in result:
            h3_cell, inc_7500, inc_7600, inc_7700, inc_all = row

            # Total should equal sum of individual types
            assert inc_all == inc_7500 + inc_7600 + inc_7700, "Total should equal sum"

            # Based on test data: inc1 is 7700, inc2 is 7600
            assert inc_7500 == 0, "No 7500 incidents in test data"
            assert inc_7600 >= 0, "Should have 7600 count"
            assert inc_7700 >= 0, "Should have 7700 count"
