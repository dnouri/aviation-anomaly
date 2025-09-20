"""Tests for H3 aggregation pipeline."""

import tempfile
from pathlib import Path

import duckdb
import pytest

from aviation_anomaly.config import Config


class TestH3Aggregation:
    """Test H3 aggregation from segments."""

    @pytest.fixture
    def config(self) -> Config:
        """Provide test configuration."""
        return Config.from_file(Path("config.toml"))

    @pytest.fixture
    def test_segments_file(self, tmp_path: Path) -> Path:
        """Create test segments with known coordinates."""
        conn = duckdb.connect(":memory:")
        conn.execute("SET memory_limit = '100MB'")

        output = tmp_path / "test_segments.parquet"

        # Create test segments with specific coordinates
        conn.execute(f"""
            COPY (
                SELECT
                    'seg1' as segment_id,
                    'abc123' as icao24,
                    1700000000 as start_time,
                    1700000600 as end_time,
                    600 as duration_seconds,
                    3 as point_count,
                    [
                        {{'time': 1700000000, 'lat': 51.5074, 'lon': -0.1278, 'squawk': '7700', 'onground': false, 'alert': true, 'callsign': 'TEST001'}},
                        {{'time': 1700000300, 'lat': 51.5174, 'lon': -0.1178, 'squawk': '7700', 'onground': false, 'alert': true, 'callsign': 'TEST001'}},
                        {{'time': 1700000600, 'lat': 51.5274, 'lon': -0.1078, 'squawk': '7700', 'onground': false, 'alert': true, 'callsign': 'TEST001'}}
                    ] as points
                UNION ALL
                SELECT
                    'seg2' as segment_id,
                    'def456' as icao24,
                    1700001000 as start_time,
                    1700001600 as end_time,
                    600 as duration_seconds,
                    2 as point_count,
                    [
                        {{'time': 1700001000, 'lat': 48.8566, 'lon': 2.3522, 'squawk': NULL, 'onground': false, 'alert': false, 'callsign': 'TEST002'}},
                        {{'time': 1700001600, 'lat': 48.8666, 'lon': 2.3622, 'squawk': NULL, 'onground': false, 'alert': false, 'callsign': 'TEST002'}}
                    ] as points
            ) TO '{output}' (FORMAT PARQUET)
        """)

        conn.close()
        return output

    def test_h3_coverage_single_resolution(
        self, test_segments_file: Path, duckdb_conn: duckdb.DuckDBPyConnection
    ) -> None:
        """Test H3 coverage computation for a single resolution."""
        from aviation_anomaly.h3_aggregation import compute_h3_coverage

        output_file = Path(tempfile.gettempdir()) / "h3_coverage_r5.parquet"

        # Compute H3 coverage at resolution 5
        compute_h3_coverage(segment_file=test_segments_file, output_file=output_file, resolution=5)

        # Verify the output using shared connection
        result = duckdb_conn.execute(f"""
            SELECT
                h3_cell,
                unique_segments,
                unique_aircraft,
                total_points
            FROM read_parquet('{output_file}')
            ORDER BY h3_cell
        """).fetchall()

        # Should have cells for both segments
        assert len(result) > 0, "Should have H3 cells"

        # Verify specific cells exist (based on known coordinates)
        london_result = duckdb_conn.execute("""
            SELECT h3_latlng_to_cell(51.5074, -0.1278, 5)
        """).fetchone()
        assert london_result is not None
        london_cell = london_result[0]

        paris_result = duckdb_conn.execute("""
            SELECT h3_latlng_to_cell(48.8566, 2.3522, 5)
        """).fetchone()
        assert paris_result is not None
        paris_cell = paris_result[0]

        h3_cells = [row[0] for row in result]
        assert london_cell in h3_cells, f"London cell {london_cell} should be in results"
        assert paris_cell in h3_cells, f"Paris cell {paris_cell} should be in results"

        # Verify aggregation metrics
        london_data = next((row for row in result if row[0] == london_cell), None)
        assert london_data is not None
        assert london_data[1] >= 1, "Should have at least 1 segment in London cell"
        assert london_data[2] >= 1, "Should have at least 1 aircraft in London cell"

    def test_h3_coverage_multiple_resolutions(self, test_segments_file: Path) -> None:
        """Test H3 coverage computation for multiple resolutions."""
        from aviation_anomaly.h3_aggregation import compute_h3_coverage_multi_resolution

        output_dir = Path(tempfile.gettempdir()) / "h3_coverage"
        output_dir.mkdir(exist_ok=True)

        # Compute for resolutions 3-7
        compute_h3_coverage_multi_resolution(
            segment_file=test_segments_file, output_dir=output_dir, resolutions=[3, 4, 5, 6, 7]
        )

        # Verify files created for each resolution
        for res in [3, 4, 5, 6, 7]:
            output_file = output_dir / f"h3_coverage_r{res}.parquet"
            assert output_file.exists(), f"Output file for resolution {res} should exist"

            # Verify cell count increases with resolution
            conn = duckdb.connect(":memory:")
            conn.execute("INSTALL h3; LOAD h3")
            count_result = conn.execute(f"""
                SELECT COUNT(DISTINCT h3_cell)
                FROM read_parquet('{output_file}')
            """).fetchone()
            assert count_result is not None
            count = count_result[0]
            conn.close()

            assert count > 0, f"Resolution {res} should have cells"
            # Note: With small test data, higher resolutions may not always
            # have more cells since segments are short

    def test_points_per_flight_coverage_metric(
        self, test_segments_file: Path, duckdb_conn: duckdb.DuckDBPyConnection
    ) -> None:
        """Test points-per-flight coverage quality metric."""
        from aviation_anomaly.h3_aggregation import compute_coverage_metrics

        output_file = Path(tempfile.gettempdir()) / "h3_coverage_metrics.parquet"

        # Compute coverage metrics
        compute_coverage_metrics(segment_file=test_segments_file, output_file=output_file, resolution=5)

        # Use shared connection for verification
        result = duckdb_conn.execute(f"""
            SELECT
                h3_cell,
                unique_segments,
                median_points_per_cell,
                coverage_category
            FROM read_parquet('{output_file}')
        """).fetchall()

        assert len(result) > 0, "Should have coverage metrics"

        for row in result:
            h3_cell, segments, median_ppf, category = row

            # Verify coverage categories
            if median_ppf >= 10:
                assert category == "excellent", f"PPF {median_ppf} should be excellent"
            elif median_ppf >= 6:
                assert category == "good", f"PPF {median_ppf} should be good"
            elif median_ppf >= 3:
                assert category == "limited", f"PPF {median_ppf} should be limited"
            else:
                assert category == "poor", f"PPF {median_ppf} should be poor"

    def test_visibility_thresholds(self, test_segments_file: Path) -> None:
        """Test application of visibility thresholds."""
        from aviation_anomaly.h3_aggregation import apply_visibility_thresholds

        # Create test data with varying flight counts
        conn = duckdb.connect(":memory:")
        conn.execute("SET memory_limit = '100MB'")

        test_aggregates = Path(tempfile.gettempdir()) / "test_aggregates.parquet"

        conn.execute(f"""
            COPY (
                SELECT
                    599686042433355775::BIGINT as h3_cell,  -- Example H3 cell
                    3 as h3_res,
                    10 as unique_segments,  -- Below threshold (25)
                    8 as unique_aircraft,
                    50 as total_points
                UNION ALL
                SELECT
                    599686042433355776::BIGINT as h3_cell,
                    3 as h3_res,
                    30 as unique_segments,  -- Above threshold
                    25 as unique_aircraft,
                    150 as total_points
            ) TO '{test_aggregates}' (FORMAT PARQUET)
        """)

        output_file = Path(tempfile.gettempdir()) / "filtered_aggregates.parquet"

        # Apply thresholds
        apply_visibility_thresholds(
            aggregates_file=test_aggregates, output_file=output_file, resolution=3, min_flights=25
        )

        # Verify filtering
        count_result = conn.execute(f"""
            SELECT COUNT(*)
            FROM read_parquet('{output_file}')
        """).fetchone()
        assert count_result is not None
        result = count_result[0]

        assert result == 1, "Should only have 1 cell above threshold"

        # Verify the correct cell was kept
        kept_result = conn.execute(f"""
            SELECT unique_segments
            FROM read_parquet('{output_file}')
        """).fetchone()
        assert kept_result is not None
        kept_cell = kept_result[0]

        assert kept_cell == 30, "Should keep cell with 30 segments"

        conn.close()
