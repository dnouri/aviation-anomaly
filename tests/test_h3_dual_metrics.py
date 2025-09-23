"""Tests for H3 dual incident metrics and incident-to-H3 mapping."""

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

        # Create test incidents (without points - they reference segments)
        conn.execute(f"""
            COPY (
                SELECT
                    'inc1' as incident_id,
                    'seg1' as segment_id,
                    'abc123' as icao24,
                    '7700' as emergency_type,
                    1700000000 as start_time,
                    1700000900 as end_time,
                    900 as duration_seconds,
                    100.0 as total_samples,
                    0.0 as ground_percentage,
                    75 as confidence_score,
                    'high' as confidence_level,
                    false as has_roller_dial,
                    NULL::VARCHAR[] as roller_dial_codes,
                    CURRENT_DATE as processing_date,
                    CURRENT_TIMESTAMP as detected_at
                UNION ALL
                SELECT
                    'inc2' as incident_id,
                    'seg2' as segment_id,
                    'def456' as icao24,
                    '7600' as emergency_type,
                    1700001000 as start_time,
                    1700001600 as end_time,
                    600 as duration_seconds,
                    80.0 as total_samples,
                    0.0 as ground_percentage,
                    60 as confidence_score,
                    'medium' as confidence_level,
                    false as has_roller_dial,
                    NULL::VARCHAR[] as roller_dial_codes,
                    CURRENT_DATE as processing_date,
                    CURRENT_TIMESTAMP as detected_at
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

        # Create segments (including those referenced by incidents)
        conn.execute(f"""
            COPY (
                -- Segment for incident 1
                SELECT
                    'seg1' as segment_id,
                    'abc123' as icao24,
                    1700000000 as start_time,
                    1700000900 as end_time,
                    900 as duration_seconds,
                    4 as point_count,
                    [
                        {{'time': 1700000000, 'lat': 51.5074, 'lon': -0.1278, 'squawk': '7700', 'onground': false, 'alert': true, 'callsign': 'TEST1'}},
                        {{'time': 1700000300, 'lat': 51.5174, 'lon': -0.1178, 'squawk': '7700', 'onground': false, 'alert': true, 'callsign': 'TEST1'}},
                        {{'time': 1700000600, 'lat': 51.5274, 'lon': -0.1078, 'squawk': '7700', 'onground': false, 'alert': true, 'callsign': 'TEST1'}},
                        {{'time': 1700000900, 'lat': 51.5374, 'lon': -0.0978, 'squawk': '7700', 'onground': false, 'alert': true, 'callsign': 'TEST1'}}
                    ] as points
                UNION ALL
                -- Segment for incident 2
                SELECT
                    'seg2' as segment_id,
                    'def456' as icao24,
                    1700001000 as start_time,
                    1700001600 as end_time,
                    600 as duration_seconds,
                    3 as point_count,
                    [
                        {{'time': 1700001000, 'lat': 51.5274, 'lon': -0.1078, 'squawk': '7600', 'onground': false, 'alert': true, 'callsign': 'TEST2'}},
                        {{'time': 1700001300, 'lat': 51.5374, 'lon': -0.0978, 'squawk': '7600', 'onground': false, 'alert': true, 'callsign': 'TEST2'}},
                        {{'time': 1700001600, 'lat': 51.5474, 'lon': -0.0878, 'squawk': '7600', 'onground': false, 'alert': true, 'callsign': 'TEST2'}}
                    ] as points
                UNION ALL
                -- Additional normal segments
                SELECT
                    'seg' || CAST(n + 2 AS VARCHAR) as segment_id,
                    'plane' || CAST(n AS VARCHAR) as icao24,
                    1700002000 + CAST(n * 1000 AS BIGINT) as start_time,
                    1700002600 + CAST(n * 1000 AS BIGINT) as end_time,
                    600 as duration_seconds,
                    3 as point_count,
                    [
                        {{'time': 1700002000 + CAST(n * 1000 AS BIGINT), 'lat': 51.5074 + CAST(n * 0.001 AS DOUBLE), 'lon': -0.1278, 'squawk': NULL, 'onground': false, 'alert': false, 'callsign': 'TEST' || CAST(n+2 AS VARCHAR)}},
                        {{'time': 1700002300 + CAST(n * 1000 AS BIGINT), 'lat': 51.5174 + CAST(n * 0.001 AS DOUBLE), 'lon': -0.1178, 'squawk': NULL, 'onground': false, 'alert': false, 'callsign': 'TEST' || CAST(n+2 AS VARCHAR)}},
                        {{'time': 1700002600 + CAST(n * 1000 AS BIGINT), 'lat': 51.5274 + CAST(n * 0.001 AS DOUBLE), 'lon': -0.1078, 'squawk': NULL, 'onground': false, 'alert': false, 'callsign': 'TEST' || CAST(n+2 AS VARCHAR)}}
                    ] as points
                FROM generate_series(1, 3) t(n)
            ) TO '{output}' (FORMAT PARQUET)
        """)

        conn.close()
        return output

    def test_dual_incident_metrics(
        self, test_incidents_file: Path, test_segments_file: Path, duckdb_conn: duckdb.DuckDBPyConnection
    ) -> None:
        """Test computation of dual incident metrics with emergency type aggregation."""
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
                unique_flights,
                incident_rate,
                emergency_types_list,
                emergency_type_diversity,
                predominant_emergency_type
            FROM read_parquet('{output_file}')
            WHERE incidents_unique > 0 OR incidents_coverage > 0
            ORDER BY h3_cell
        """).fetchall()

        assert len(result) > 0, "Should have H3 cells with incidents"

        # Check that metrics are computed correctly
        for row in result:
            h3_cell, inc_unique, inc_coverage, flights, incident_rate, types_list, type_div, predominant = row

            # incidents_unique counts unique incidents per cell (for rate calculation)
            # incidents_coverage counts all incident observations (for heatmap)
            assert inc_coverage >= inc_unique, "Coverage should be >= unique"

            # Rate should be calculated correctly
            if flights > 0:
                expected_rate = inc_unique / flights
                assert abs(incident_rate - expected_rate) < 0.001, "Incident rate calculation"

            # Verify emergency type fields
            if inc_unique > 0:
                assert types_list is not None, "Should have emergency types list"
                assert type_div >= 1, "Should have at least one emergency type"
                assert predominant in ["7500", "7600", "7700"], "Predominant type should be valid"

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

    def test_incident_to_h3_mapping_generation(self, test_incidents_file: Path, test_segments_file: Path) -> None:
        """Test that incident-to-H3 mapping table is generated alongside metrics."""
        from aviation_anomaly.h3_aggregation import compute_dual_incident_metrics

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            metrics_file = output_dir / "h3_incidents_r5.parquet"
            mapping_file = output_dir / "incident_h3_mapping_r5.parquet"

            # Run aggregation (should produce both metrics and mapping)
            compute_dual_incident_metrics(
                incidents_file=test_incidents_file,
                segments_file=test_segments_file,
                output_file=metrics_file,
                resolution=5,
            )

            # Check metrics file exists (existing behavior)
            assert metrics_file.exists(), "Metrics file should be created"

            # Check mapping file exists (NEW behavior - will be RED)
            assert mapping_file.exists(), "Mapping file should be created"

            # Verify mapping structure
            conn = duckdb.connect(":memory:")
            result = conn.execute(f"""
                SELECT
                    COUNT(*) as row_count,
                    COUNT(DISTINCT incident_id) as unique_incidents,
                    COUNT(DISTINCT h3_cell) as unique_cells
                FROM read_parquet('{mapping_file}')
            """).fetchone()

            assert result is not None
            row_count, unique_incidents, unique_cells = result

            # We have 2 test incidents
            assert unique_incidents == 2, "Should map both test incidents"
            assert unique_cells > 0, "Should have H3 cells"
            assert row_count >= unique_incidents, "Can have multiple cells per incident"

            # Verify schema
            schema = conn.execute(f"DESCRIBE SELECT * FROM '{mapping_file}'").fetchall()
            column_names = [col[0] for col in schema]

            assert "incident_id" in column_names
            assert "h3_cell" in column_names
            assert "h3_res" in column_names
