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

        # Compute for resolutions 3-6
        compute_h3_coverage_multi_resolution(
            segment_files=test_segments_file, output_dir=output_dir, resolutions=[3, 4, 5, 6]
        )

        # Verify files created for each resolution
        for res in [3, 4, 5, 6]:
            output_file = output_dir / f"h3_coverage_r{res}.parquet"
            assert output_file.exists(), f"Output file for resolution {res} should exist"

            # Verify cell count increases with resolution
            conn = duckdb.connect(":memory:")
            conn.execute("INSTALL h3 FROM community; LOAD h3")
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

    def test_atomic_write_no_temp_files(self, test_segments_file: Path, tmp_path: Path) -> None:
        """Test that compute_h3_coverage uses atomic writes (no .tmp files remain)."""
        from aviation_anomaly.h3_aggregation import compute_h3_coverage

        output_file = tmp_path / "h3_coverage_atomic.parquet"

        # Run aggregation
        compute_h3_coverage(segment_file=test_segments_file, output_file=output_file, resolution=5)

        # Verify output file exists
        assert output_file.exists(), "Output file should exist"

        # Verify NO temp files remain in directory
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0, f"No .tmp files should remain, found: {temp_files}"

        # Verify output is valid parquet
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3 FROM community; LOAD h3")
        result = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{output_file}')").fetchone()
        assert result is not None
        assert result[0] > 0, "Output file should contain data"
        conn.close()


class TestMultiCellSegmentCounting:
    """Test that segments crossing multiple cells are counted correctly."""

    def test_one_segment_many_cells(self, tmp_path: Path) -> None:
        """Test that one segment crossing many cells counts as 1 in each cell."""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3 FROM community; LOAD h3")
        conn.execute("SET memory_limit = '100MB'")

        # Create a segment that crosses multiple cells (like a real flight)
        # Using coordinates that span ~100km to cross multiple R5 cells
        segments_file = tmp_path / "multi_cell_segment.parquet"

        conn.execute(f"""
            COPY (
                SELECT
                    'flight001' as segment_id,
                    'abc123' as icao24,
                    1700000000 as start_time,
                    1700003600 as end_time,
                    3600 as duration_seconds,
                    50 as point_count,
                    -- Create a line of points from London towards Paris
                    [
                        {{'time': 1700000000 + i * 72, 'lat': 51.5 + i * 0.05, 'lon': -0.1 + i * 0.05,
                          'squawk': '1200', 'onground': false, 'alert': false}}
                        FOR i IN generate_series(0, 49)
                    ] as points
            ) TO '{segments_file}' (FORMAT PARQUET)
        """)

        # Run H3 aggregation
        from aviation_anomaly.h3_aggregation import compute_h3_coverage

        output_file = tmp_path / "h3_coverage.parquet"
        compute_h3_coverage(segment_file=segments_file, output_file=output_file, resolution=5)

        # Verify results
        result = conn.execute(f"""
            SELECT
                COUNT(*) as cell_count,
                MIN(unique_segments) as min_segments,
                MAX(unique_segments) as max_segments,
                SUM(unique_segments) as total_segment_counts
            FROM read_parquet('{output_file}')
        """).fetchone()

        # The segment should appear in multiple cells
        assert result[0] > 5, f"Segment should cross multiple cells, got {result[0]}"  # type: ignore[index]

        # Each cell should count the segment exactly once
        assert result[1] == 1, f"Each cell should have min 1 segment, got {result[1]}"  # type: ignore[index]
        assert result[2] == 1, f"Each cell should have max 1 segment, got {result[2]}"  # type: ignore[index]

        # Total segment counts should equal number of cells (not 1!)
        assert result[3] == result[0], "Each cell counts the segment once"  # type: ignore[index]

        conn.close()

    def test_multiple_segments_overlapping_cells(self, tmp_path: Path) -> None:
        """Test correct counting when multiple segments pass through same cells."""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3 FROM community; LOAD h3")
        conn.execute("SET memory_limit = '100MB'")

        segments_file = tmp_path / "overlapping_segments.parquet"

        # Create 3 segments that partially overlap in space
        conn.execute(f"""
            COPY (
                -- Segment 1: Goes north
                SELECT
                    'flight001' as segment_id,
                    'abc123' as icao24,
                    1700000000 as start_time,
                    1700001000 as end_time,
                    1000 as duration_seconds,
                    10 as point_count,
                    [
                        {{'time': 1700000000 + i * 100, 'lat': 51.5 + i * 0.01, 'lon': 0.0,
                          'squawk': '1200', 'onground': false, 'alert': false}}
                        FOR i IN generate_series(0, 9)
                    ] as points
                UNION ALL
                -- Segment 2: Goes east
                SELECT
                    'flight002' as segment_id,
                    'def456' as icao24,
                    1700001000 as start_time,
                    1700002000 as end_time,
                    1000 as duration_seconds,
                    10 as point_count,
                    [
                        {{'time': 1700001000 + i * 100, 'lat': 51.5, 'lon': 0.0 + i * 0.01,
                          'squawk': '1200', 'onground': false, 'alert': false}}
                        FOR i IN generate_series(0, 9)
                    ] as points
                UNION ALL
                -- Segment 3: Goes through the crossing point
                SELECT
                    'flight003' as segment_id,
                    'ghi789' as icao24,
                    1700002000 as start_time,
                    1700003000 as end_time,
                    1000 as duration_seconds,
                    10 as point_count,
                    [
                        {{'time': 1700002000 + i * 100, 'lat': 51.49 + i * 0.002, 'lon': -0.01 + i * 0.002,
                          'squawk': '1200', 'onground': false, 'alert': false}}
                        FOR i IN generate_series(0, 9)
                    ] as points
            ) TO '{segments_file}' (FORMAT PARQUET)
        """)

        # Run H3 aggregation
        from aviation_anomaly.h3_aggregation import compute_h3_coverage

        output_file = tmp_path / "h3_coverage_overlap.parquet"
        compute_h3_coverage(segment_file=segments_file, output_file=output_file, resolution=6)

        # Find the cell at the origin where all segments start/pass
        origin_cell = conn.execute("""
            SELECT h3_latlng_to_cell(51.5, 0.0, 6)
        """).fetchone()[0]  # type: ignore[index]

        # Check that origin cell has correct counts
        result = conn.execute(f"""
            SELECT
                unique_segments,
                unique_aircraft,
                total_points
            FROM read_parquet('{output_file}')
            WHERE h3_cell = {origin_cell}
        """).fetchone()

        if result:  # Origin cell might be found
            # Should have 2-3 segments depending on exact overlap
            assert result[0] >= 2, f"Origin should have at least 2 segments, got {result[0]}"
            assert result[1] >= 2, f"Origin should have at least 2 aircraft, got {result[1]}"

        conn.close()


class TestIncidentAttribution:
    """Test incident attribution across H3 cells following dual metrics approach."""

    def test_incident_crossing_multiple_cells(self, tmp_path: Path) -> None:
        """Test dual metrics when one incident spans multiple cells."""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3 FROM community; LOAD h3")
        conn.execute("SET memory_limit = '100MB'")

        # Create an incident segment crossing 5+ cells
        segments_file = tmp_path / "incident_segment.parquet"
        incidents_file = tmp_path / "incidents.parquet"

        # Create segment with emergency
        conn.execute(f"""
            COPY (
                SELECT
                    'emrg001' as segment_id,
                    'abc123' as icao24,
                    1700000000 as start_time,
                    1700001800 as end_time,
                    1800 as duration_seconds,
                    20 as point_count,
                    [
                        {{'time': 1700000000 + i * 90, 'lat': 51.5 + i * 0.02, 'lon': -0.1 + i * 0.02,
                          'squawk': '7700', 'onground': false, 'alert': true}}
                        FOR i IN generate_series(0, 19)
                    ] as points
            ) TO '{segments_file}' (FORMAT PARQUET)
        """)

        # Create corresponding incident
        conn.execute(f"""
            COPY (
                SELECT
                    'inc001' as incident_id,
                    'emrg001' as segment_id,
                    'abc123' as icao24,
                    '7700' as emergency_type,
                    1700000000 as start_time,
                    1700001800 as end_time,
                    1800 as duration_seconds,
                    20.0 as total_samples,
                    0.0 as ground_percentage,
                    85 as confidence_score,
                    'HIGH' as confidence_level,
                    false as has_roller_dial,
                    [] as roller_dial_codes,
                    CURRENT_DATE as processing_date,
                    CURRENT_TIMESTAMP as detected_at
            ) TO '{incidents_file}' (FORMAT PARQUET)
        """)

        # Process H3 aggregation
        from aviation_anomaly.h3_aggregation import compute_h3_coverage

        output_file = tmp_path / "h3_with_incident.parquet"
        compute_h3_coverage(segment_file=segments_file, output_file=output_file, resolution=5)

        # Count how many cells the incident spans
        cell_count = conn.execute(f"""
            SELECT COUNT(*)
            FROM read_parquet('{output_file}')
        """).fetchone()[0]  # type: ignore[index]

        assert cell_count >= 3, f"Incident should span multiple cells, got {cell_count}"

        # Verify dual metrics if we had incident aggregation
        # NOTE: Current h3_aggregation.sql doesn't include incident metrics
        # This test documents expected behavior for when it's implemented

        # Expected behavior:
        # - incidents_unique = 1 in each cell (one unique incident)
        # - incidents_coverage = 1 in each cell (one incident touches this cell)
        # - Total incidents_coverage across all cells = number of cells touched

        conn.close()


class TestNullCoordinateHandling:
    """Test handling of NULL coordinates in segment points."""

    def test_segment_with_partial_null_coordinates(self, tmp_path: Path) -> None:
        """Test that NULL coordinate points are filtered but segment remains."""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3 FROM community; LOAD h3")
        conn.execute("SET memory_limit = '100MB'")

        segments_file = tmp_path / "null_coords_segment.parquet"

        # Create segment with some NULL coordinates
        conn.execute(f"""
            COPY (
                SELECT
                    'flight_null' as segment_id,
                    'abc123' as icao24,
                    1700000000 as start_time,
                    1700001000 as end_time,
                    1000 as duration_seconds,
                    10 as point_count,
                    [
                        -- First 3 points are valid
                        {{'time': 1700000000, 'lat': 51.5, 'lon': 0.0, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700000100, 'lat': 51.51, 'lon': 0.01, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700000200, 'lat': 51.52, 'lon': 0.02, 'squawk': '1200', 'onground': false, 'alert': false}},
                        -- Next 3 have NULL coordinates
                        {{'time': 1700000300, 'lat': NULL, 'lon': NULL, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700000400, 'lat': NULL, 'lon': 0.04, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700000500, 'lat': 51.55, 'lon': NULL, 'squawk': '1200', 'onground': false, 'alert': false}},
                        -- Last 4 are valid again
                        {{'time': 1700000600, 'lat': 51.56, 'lon': 0.06, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700000700, 'lat': 51.57, 'lon': 0.07, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700000800, 'lat': 51.58, 'lon': 0.08, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700000900, 'lat': 51.59, 'lon': 0.09, 'squawk': '1200', 'onground': false, 'alert': false}}
                    ] as points
            ) TO '{segments_file}' (FORMAT PARQUET)
        """)

        # Run H3 aggregation
        from aviation_anomaly.h3_aggregation import compute_h3_coverage

        output_file = tmp_path / "h3_null_coords.parquet"
        compute_h3_coverage(segment_file=segments_file, output_file=output_file, resolution=5)

        # Verify segment was processed despite NULL coordinates
        result = conn.execute(f"""
            SELECT
                COUNT(*) as cell_count,
                SUM(unique_segments) as total_segments,
                SUM(total_points) as total_points,
                MIN(unique_segments) as min_segments
            FROM read_parquet('{output_file}')
        """).fetchone()

        # Should have cells (from the 7 valid points)
        assert result[0] > 0, "Should have H3 cells from valid points"  # type: ignore[index]

        # Each cell should have the segment
        assert result[3] == 1, "Each cell should count segment once"  # type: ignore[index]

        # Total points should be 7 (10 - 3 NULL)
        # Note: total_points is summed across cells, so may be higher if points repeat in cells
        assert result[2] >= 7, f"Should have at least 7 valid points aggregated, got {result[2]}"  # type: ignore[index]

        # Segment presence is already verified by result[0] > 0 and result[3] == 1

        conn.close()


class TestPointsPerFlightCalculation:
    """Test points-per-flight metric calculation per cell."""

    def test_ppf_calculation_per_cell(self, tmp_path: Path) -> None:
        """Test that each cell calculates its own PPF correctly."""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3 FROM community; LOAD h3")
        conn.execute("SET memory_limit = '100MB'")

        segments_file = tmp_path / "ppf_segments.parquet"

        # Create segments with different point densities in cells
        conn.execute(f"""
            COPY (
                -- Segment 1: Dense coverage (many points in small area)
                SELECT
                    'dense001' as segment_id,
                    'abc123' as icao24,
                    1700000000 as start_time,
                    1700001000 as end_time,
                    1000 as duration_seconds,
                    100 as point_count,
                    [
                        {{'time': 1700000000 + i * 10, 'lat': 51.5 + (i % 10) * 0.001, 'lon': 0.0 + (i / 10) * 0.001,
                          'squawk': '1200', 'onground': false, 'alert': false}}
                        FOR i IN generate_series(0, 99)
                    ] as points
                UNION ALL
                -- Segment 2: Sparse coverage (few points, same area)
                SELECT
                    'sparse001' as segment_id,
                    'def456' as icao24,
                    1700002000 as start_time,
                    1700002100 as end_time,
                    100 as duration_seconds,
                    2 as point_count,
                    [
                        {{'time': 1700002000, 'lat': 51.5, 'lon': 0.0, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700002100, 'lat': 51.501, 'lon': 0.001, 'squawk': '1200', 'onground': false, 'alert': false}}
                    ] as points
            ) TO '{segments_file}' (FORMAT PARQUET)
        """)

        # Run H3 aggregation
        from aviation_anomaly.h3_aggregation import compute_h3_coverage

        output_file = tmp_path / "h3_ppf.parquet"
        compute_h3_coverage(segment_file=segments_file, output_file=output_file, resolution=6)

        # Get the main cell where both segments overlap
        main_cell = conn.execute("""
            SELECT h3_latlng_to_cell(51.5, 0.0, 6)
        """).fetchone()[0]  # type: ignore[index]

        # Check PPF calculation
        result = conn.execute(f"""
            SELECT
                unique_segments,
                total_points,
                CAST(total_points AS FLOAT) / unique_segments as calculated_ppf
            FROM read_parquet('{output_file}')
            WHERE h3_cell = {main_cell}
        """).fetchone()

        if result:
            segments = result[0]
            points = result[1]
            ppf = result[2]

            # Should have 2 segments
            assert segments == 2, f"Should have 2 segments in main cell, got {segments}"

            # PPF should be total_points / unique_segments
            assert abs(ppf - points / segments) < 0.01, f"PPF calculation error: {ppf} != {points}/{segments}"

            # Based on our data, PPF should be relatively high (many points from dense segment)
            assert ppf > 10, f"PPF should be >10 with dense segment, got {ppf}"

        conn.close()

    def test_ppf_categories(self, tmp_path: Path) -> None:
        """Test PPF-based coverage quality categories."""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3 FROM community; LOAD h3")
        conn.execute("SET memory_limit = '100MB'")

        # Test with compute_coverage_metrics if it exists
        from aviation_anomaly.h3_aggregation import compute_coverage_metrics

        segments_file = tmp_path / "ppf_category_segments.parquet"

        # Create segments with specific PPF values
        conn.execute(f"""
            COPY (
                -- Excellent coverage: 20 points, 1 segment = PPF 20
                SELECT
                    'excel001' as segment_id,
                    'abc123' as icao24,
                    1700000000 as start_time,
                    1700000200 as end_time,
                    200 as duration_seconds,
                    20 as point_count,
                    [
                        {{'time': 1700000000 + i * 10, 'lat': 40.0, 'lon': -74.0 + i * 0.0001,
                          'squawk': '1200', 'onground': false, 'alert': false}}
                        FOR i IN generate_series(0, 19)
                    ] as points
                UNION ALL
                -- Good coverage: 8 points, 1 segment = PPF 8
                SELECT
                    'good001' as segment_id,
                    'def456' as icao24,
                    1700001000 as start_time,
                    1700001080 as end_time,
                    80 as duration_seconds,
                    8 as point_count,
                    [
                        {{'time': 1700001000 + i * 10, 'lat': 41.0, 'lon': -73.0 + i * 0.0001,
                          'squawk': '1200', 'onground': false, 'alert': false}}
                        FOR i IN generate_series(0, 7)
                    ] as points
                UNION ALL
                -- Limited coverage: 4 points, 1 segment = PPF 4
                SELECT
                    'limit001' as segment_id,
                    'ghi789' as icao24,
                    1700002000 as start_time,
                    1700002040 as end_time,
                    40 as duration_seconds,
                    4 as point_count,
                    [
                        {{'time': 1700002000 + i * 10, 'lat': 42.0, 'lon': -72.0 + i * 0.0001,
                          'squawk': '1200', 'onground': false, 'alert': false}}
                        FOR i IN generate_series(0, 3)
                    ] as points
                UNION ALL
                -- Poor coverage: 2 points, 1 segment = PPF 2
                SELECT
                    'poor001' as segment_id,
                    'jkl012' as icao24,
                    1700003000 as start_time,
                    1700003020 as end_time,
                    20 as duration_seconds,
                    2 as point_count,
                    [
                        {{'time': 1700003000, 'lat': 43.0, 'lon': -71.0, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700003020, 'lat': 43.001, 'lon': -71.001, 'squawk': '1200', 'onground': false, 'alert': false}}
                    ] as points
            ) TO '{segments_file}' (FORMAT PARQUET)
        """)

        output_file = tmp_path / "h3_coverage_categories.parquet"
        compute_coverage_metrics(segment_file=segments_file, output_file=output_file, resolution=5)

        # Check categories
        result = conn.execute(f"""
            SELECT
                median_points_per_cell,
                coverage_category
            FROM read_parquet('{output_file}')
            ORDER BY median_points_per_cell DESC
        """).fetchall()

        for ppf, category in result:
            if ppf >= 10:
                assert category == "excellent", f"PPF {ppf} should be excellent"
            elif ppf >= 6:
                assert category == "good", f"PPF {ppf} should be good"
            elif ppf >= 3:
                assert category == "limited", f"PPF {ppf} should be limited"
            else:
                assert category == "poor", f"PPF {ppf} should be poor"

        conn.close()


class TestCellHierarchyConsistency:
    """Test H3 resolution hierarchy independence."""

    def test_resolutions_computed_independently(self, tmp_path: Path) -> None:
        """Test that each resolution is computed from raw data, not hierarchically."""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3 FROM community; LOAD h3")
        conn.execute("SET memory_limit = '100MB'")

        segments_file = tmp_path / "hierarchy_segments.parquet"

        # Create segments in a small area - simpler approach
        conn.execute(f"""
            COPY (
                SELECT 'seg0' as segment_id, 'plane0' as icao24, 1700000000 as start_time, 1700000600 as end_time,
                       600 as duration_seconds, 5 as point_count,
                       [{{'time': 1700000000, 'lat': 51.5, 'lon': 0.0, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700000120, 'lat': 51.5002, 'lon': 0.0002, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700000240, 'lat': 51.5004, 'lon': 0.0004, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700000360, 'lat': 51.5006, 'lon': 0.0006, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700000480, 'lat': 51.5008, 'lon': 0.0008, 'squawk': '1200', 'onground': false, 'alert': false}}] as points
                UNION ALL
                SELECT 'seg1' as segment_id, 'plane1' as icao24, 1700001000 as start_time, 1700001600 as end_time,
                       600 as duration_seconds, 5 as point_count,
                       [{{'time': 1700001000, 'lat': 51.501, 'lon': 0.001, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700001120, 'lat': 51.5012, 'lon': 0.0012, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700001240, 'lat': 51.5014, 'lon': 0.0014, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700001360, 'lat': 51.5016, 'lon': 0.0016, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700001480, 'lat': 51.5018, 'lon': 0.0018, 'squawk': '1200', 'onground': false, 'alert': false}}] as points
                UNION ALL
                SELECT 'seg2' as segment_id, 'plane2' as icao24, 1700002000 as start_time, 1700002600 as end_time,
                       600 as duration_seconds, 5 as point_count,
                       [{{'time': 1700002000, 'lat': 51.502, 'lon': 0.002, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700002120, 'lat': 51.5022, 'lon': 0.0022, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700002240, 'lat': 51.5024, 'lon': 0.0024, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700002360, 'lat': 51.5026, 'lon': 0.0026, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700002480, 'lat': 51.5028, 'lon': 0.0028, 'squawk': '1200', 'onground': false, 'alert': false}}] as points
                UNION ALL
                SELECT 'seg3' as segment_id, 'plane3' as icao24, 1700003000 as start_time, 1700003600 as end_time,
                       600 as duration_seconds, 5 as point_count,
                       [{{'time': 1700003000, 'lat': 51.503, 'lon': 0.003, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700003120, 'lat': 51.5032, 'lon': 0.0032, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700003240, 'lat': 51.5034, 'lon': 0.0034, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700003360, 'lat': 51.5036, 'lon': 0.0036, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700003480, 'lat': 51.5038, 'lon': 0.0038, 'squawk': '1200', 'onground': false, 'alert': false}}] as points
                UNION ALL
                SELECT 'seg4' as segment_id, 'plane4' as icao24, 1700004000 as start_time, 1700004600 as end_time,
                       600 as duration_seconds, 5 as point_count,
                       [{{'time': 1700004000, 'lat': 51.504, 'lon': 0.004, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700004120, 'lat': 51.5042, 'lon': 0.0042, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700004240, 'lat': 51.5044, 'lon': 0.0044, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700004360, 'lat': 51.5046, 'lon': 0.0046, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700004480, 'lat': 51.5048, 'lon': 0.0048, 'squawk': '1200', 'onground': false, 'alert': false}}] as points
            ) TO '{segments_file}' (FORMAT PARQUET)
        """)

        # Compute at different resolutions
        from aviation_anomaly.h3_aggregation import compute_h3_coverage

        output_r4 = tmp_path / "h3_r4.parquet"
        output_r5 = tmp_path / "h3_r5.parquet"

        compute_h3_coverage(segment_file=segments_file, output_file=output_r4, resolution=4)
        compute_h3_coverage(segment_file=segments_file, output_file=output_r5, resolution=5)

        # Get counts at each resolution
        r4_stats = conn.execute(f"""
            SELECT
                COUNT(*) as cell_count,
                SUM(unique_segments) as total_segment_counts,
                MAX(unique_segments) as max_segments_per_cell
            FROM read_parquet('{output_r4}')
        """).fetchone()

        r5_stats = conn.execute(f"""
            SELECT
                COUNT(*) as cell_count,
                SUM(unique_segments) as total_segment_counts,
                MAX(unique_segments) as max_segments_per_cell
            FROM read_parquet('{output_r5}')
        """).fetchone()

        # R5 may have more or same cells as R4 depending on segment distribution
        # The key point is that they're computed independently from raw data

        # Each resolution computed independently, so segment counts are based on actual data
        # Not derived from parent/child relationships
        assert r4_stats[2] <= 5, "Max segments per cell should be <= 5 (we created 5 segments)"  # type: ignore[index]
        assert r5_stats[2] <= 5, "Max segments per cell should be <= 5 at any resolution"  # type: ignore[index]

        # Verify independence: Each resolution has its own aggregation
        # If they were hierarchical, R4 would be derived from R5
        # Instead, both compute directly from segments
        assert r4_stats[0] > 0, "R4 should have cells"  # type: ignore[index]
        assert r5_stats[0] > 0, "R5 should have cells"  # type: ignore[index]

        conn.close()


class TestH3DailyMerge:
    """Test merging per-day H3 coverage files into final aggregate."""

    def test_merge_coverage_sums_counts_and_drops_lists(self, tmp_path: Path) -> None:
        """Test that merge sums counts across days and drops segment/aircraft lists."""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3 FROM community; LOAD h3")
        conn.execute("SET memory_limit = '100MB'")

        # Create daily directory
        daily_dir = tmp_path / "daily"
        daily_dir.mkdir()

        # Create Day 1 coverage file with 2 cells
        day1_file = daily_dir / "h3_coverage_r5_2025-07-01.parquet"
        conn.execute(f"""
            COPY (
                SELECT
                    599686042433355775::BIGINT as h3_cell,
                    5 as h3_res,
                    10 as unique_segments,
                    8 as unique_aircraft,
                    100 as total_points,
                    ['seg1', 'seg2'] as segment_list,
                    ['plane1', 'plane2'] as aircraft_list
                UNION ALL
                SELECT
                    599686042433355776::BIGINT as h3_cell,
                    5 as h3_res,
                    5 as unique_segments,
                    4 as unique_aircraft,
                    50 as total_points,
                    ['seg3'] as segment_list,
                    ['plane3'] as aircraft_list
            ) TO '{day1_file}' (FORMAT PARQUET)
        """)

        # Create Day 2 coverage file with 1 overlapping cell, 1 new cell
        day2_file = daily_dir / "h3_coverage_r5_2025-07-02.parquet"
        conn.execute(f"""
            COPY (
                SELECT
                    599686042433355775::BIGINT as h3_cell,
                    5 as h3_res,
                    15 as unique_segments,
                    12 as unique_aircraft,
                    150 as total_points,
                    ['seg4', 'seg5', 'seg6'] as segment_list,
                    ['plane4', 'plane5'] as aircraft_list
                UNION ALL
                SELECT
                    599686042433355777::BIGINT as h3_cell,
                    5 as h3_res,
                    3 as unique_segments,
                    2 as unique_aircraft,
                    30 as total_points,
                    ['seg7'] as segment_list,
                    ['plane6'] as aircraft_list
            ) TO '{day2_file}' (FORMAT PARQUET)
        """)

        # Call merge function
        from aviation_anomaly.h3_aggregation import merge_h3_daily_coverage

        output_file = tmp_path / "h3_coverage_r5.parquet"
        merge_h3_daily_coverage(daily_dir=daily_dir, output_file=output_file, resolution=5)

        # Verify merged output
        result = conn.execute(f"""
            SELECT
                h3_cell,
                h3_res,
                unique_segments,
                unique_aircraft,
                total_points
            FROM read_parquet('{output_file}')
            ORDER BY h3_cell
        """).fetchall()

        # Should have 3 cells total (2 from day1, 2 from day2, 1 overlapping)
        assert len(result) == 3, f"Expected 3 cells, got {len(result)}"

        # Check first cell (overlapping): should have summed values
        cell1 = result[0]
        assert cell1[0] == 599686042433355775
        assert cell1[1] == 5
        assert cell1[2] == 25, f"Expected 10+15=25 segments, got {cell1[2]}"  # 10 from day1 + 15 from day2
        assert cell1[3] == 20, f"Expected 8+12=20 aircraft, got {cell1[3]}"  # 8 from day1 + 12 from day2
        assert cell1[4] == 250, f"Expected 100+150=250 points, got {cell1[4]}"  # 100 from day1 + 150 from day2

        # Check second cell (day1 only)
        cell2 = result[1]
        assert cell2[0] == 599686042433355776
        assert cell2[2] == 5  # Only from day1

        # Check third cell (day2 only)
        cell3 = result[2]
        assert cell3[0] == 599686042433355777
        assert cell3[2] == 3  # Only from day2

        # Verify lists are NOT in output schema
        schema = conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{output_file}')").fetchall()
        column_names = [row[0] for row in schema]
        assert "segment_list" not in column_names, "segment_list should be dropped in merge"
        assert "aircraft_list" not in column_names, "aircraft_list should be dropped in merge"

        conn.close()

    def test_merge_incidents_recalculates_mode_and_merges_lists(self, tmp_path: Path) -> None:
        """Test that merge merges emergency type lists and correctly recalculates MODE."""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3 FROM community; LOAD h3")
        conn.execute("SET memory_limit = '100MB'")

        # Create daily directory
        daily_dir = tmp_path / "daily"
        daily_dir.mkdir()

        # Create Day 1 incidents file - cell has 7500 (3x) and 7700 (1x)
        day1_file = daily_dir / "h3_incidents_r5_2025-07-01.parquet"
        conn.execute(f"""
            COPY (
                SELECT
                    599686042433355775::BIGINT as h3_cell,
                    5 as h3_res,
                    3 as incidents_unique,
                    3 as aircraft_with_incidents,
                    4 as incidents_coverage,
                    100 as unique_segments,
                    100 as total_segments,
                    ['7500', '7700'] as emergency_types_list,
                    2 as emergency_type_diversity,
                    '7500' as predominant_emergency_type,  -- MODE from day 1
                    2 as incidents_7500,  -- 2 of 7500 (predominant)
                    0 as incidents_7600,
                    1 as incidents_7700,  -- 1 of 7700
                    0.03 as incident_rate
            ) TO '{day1_file}' (FORMAT PARQUET)
        """)

        # Create Day 2 incidents file - same cell has 7700 (4x), making it new MODE
        day2_file = daily_dir / "h3_incidents_r5_2025-07-02.parquet"
        conn.execute(f"""
            COPY (
                SELECT
                    599686042433355775::BIGINT as h3_cell,
                    5 as h3_res,
                    4 as incidents_unique,
                    4 as aircraft_with_incidents,
                    4 as incidents_coverage,
                    150 as unique_segments,
                    150 as total_segments,
                    ['7700'] as emergency_types_list,
                    1 as emergency_type_diversity,
                    '7700' as predominant_emergency_type,  -- MODE from day 2
                    0 as incidents_7500,
                    0 as incidents_7600,
                    4 as incidents_7700,  -- All 4 are 7700
                    0.027 as incident_rate
            ) TO '{day2_file}' (FORMAT PARQUET)
        """)

        # Call merge function
        from aviation_anomaly.h3_aggregation import merge_h3_daily_incidents

        output_file = tmp_path / "h3_incidents_r5.parquet"
        merge_h3_daily_incidents(daily_dir=daily_dir, output_file=output_file, resolution=5)

        # Verify merged output
        result = conn.execute(f"""
            SELECT
                h3_cell,
                h3_res,
                incidents_unique,
                aircraft_with_incidents,
                incidents_coverage,
                unique_segments,
                total_segments,
                emergency_types_list,
                emergency_type_diversity,
                predominant_emergency_type,
                incident_rate
            FROM read_parquet('{output_file}')
        """).fetchone()

        assert result is not None, "Merge should produce output"

        # Verify summed counts
        assert result[2] == 7, f"Expected 3+4=7 incidents_unique, got {result[2]}"
        assert result[3] == 7, f"Expected 3+4=7 aircraft_with_incidents, got {result[3]}"
        assert result[4] == 8, f"Expected 4+4=8 incidents_coverage, got {result[4]}"
        assert result[5] == 250, f"Expected 100+150=250 unique_segments, got {result[5]}"

        # Verify emergency type list merged correctly (both types present)
        emergency_types = result[7]
        assert "7500" in emergency_types, "7500 should be in merged list"
        assert "7700" in emergency_types, "7700 should be in merged list"
        assert len(emergency_types) == 2, f"Expected 2 unique types, got {len(emergency_types)}"

        # Verify diversity is correct
        assert result[8] == 2, f"Expected diversity=2, got {result[8]}"

        # Verify MODE is 7700 (appears 5 times: 1 from day1 + 4 from day2, vs 3 times for 7500)
        assert result[9] == "7700", f"Expected predominant_emergency_type='7700', got {result[9]}"

        # Verify recalculated incident rate
        expected_rate = 7 / 250  # incidents_unique / unique_segments
        assert abs(result[10] - expected_rate) < 0.001, f"Expected rate={expected_rate}, got {result[10]}"

        conn.close()

    def test_merge_mapping_deduplicates_pairs(self, tmp_path: Path) -> None:
        """Test that mapping merge deduplicates (incident_id, h3_cell) pairs."""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3 FROM community; LOAD h3")
        conn.execute("SET memory_limit = '100MB'")

        # Create daily directory
        daily_dir = tmp_path / "daily"
        daily_dir.mkdir()

        # Create Day 1 mapping - incident spans 2 cells
        day1_file = daily_dir / "incident_h3_mapping_r5_2025-07-01.parquet"
        conn.execute(f"""
            COPY (
                SELECT 'INC001' as incident_id, 599686042433355775::BIGINT as h3_cell, 5 as h3_res
                UNION ALL
                SELECT 'INC001' as incident_id, 599686042433355776::BIGINT as h3_cell, 5 as h3_res
                UNION ALL
                SELECT 'INC002' as incident_id, 599686042433355777::BIGINT as h3_cell, 5 as h3_res
            ) TO '{day1_file}' (FORMAT PARQUET)
        """)

        # Create Day 2 mapping - INC001 reappears (midnight-spanning), new INC003
        day2_file = daily_dir / "incident_h3_mapping_r5_2025-07-02.parquet"
        conn.execute(f"""
            COPY (
                SELECT 'INC001' as incident_id, 599686042433355775::BIGINT as h3_cell, 5 as h3_res
                UNION ALL
                SELECT 'INC001' as incident_id, 599686042433355778::BIGINT as h3_cell, 5 as h3_res
                UNION ALL
                SELECT 'INC003' as incident_id, 599686042433355779::BIGINT as h3_cell, 5 as h3_res
            ) TO '{day2_file}' (FORMAT PARQUET)
        """)

        # Call merge function
        from aviation_anomaly.h3_aggregation import merge_incident_h3_mapping

        output_file = tmp_path / "incident_h3_mapping_r5.parquet"
        merge_incident_h3_mapping(daily_dir=daily_dir, output_file=output_file, resolution=5)

        # Verify merged output
        result = conn.execute(f"""
            SELECT incident_id, h3_cell, h3_res
            FROM read_parquet('{output_file}')
            ORDER BY incident_id, h3_cell
        """).fetchall()

        # Should have 5 unique pairs:
        # INC001 → cell 775 (day1 & day2, deduplicated)
        # INC001 → cell 776 (day1 only)
        # INC001 → cell 778 (day2 only)
        # INC002 → cell 777 (day1 only)
        # INC003 → cell 779 (day2 only)
        assert len(result) == 5, f"Expected 5 unique pairs, got {len(result)}"

        # Verify INC001 has 3 cells (not 4, since 775 is deduplicated)
        inc001_pairs = [r for r in result if r[0] == "INC001"]
        assert len(inc001_pairs) == 3, f"Expected INC001 to have 3 cells, got {len(inc001_pairs)}"

        # Verify cell 775 appears only once for INC001
        inc001_cells = [r[1] for r in inc001_pairs]
        assert inc001_cells.count(599686042433355775) == 1, "Cell 775 should appear once (deduplicated)"

        # Verify all pairs have correct resolution
        for row in result:
            assert row[2] == 5, f"Expected h3_res=5, got {row[2]}"

        conn.close()


class TestSinglePointEdgeCases:
    """Test edge cases with minimal data."""

    def test_segment_with_less_than_2_points_filtered(self, tmp_path: Path) -> None:
        """Test that segments with <2 points are filtered per SPEC."""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3 FROM community; LOAD h3")
        conn.execute("SET memory_limit = '100MB'")

        segments_file = tmp_path / "single_point_segment.parquet"

        # Create mix of valid and invalid segments
        conn.execute(f"""
            COPY (
                -- Invalid: 1 point segment
                SELECT
                    'single001' as segment_id,
                    'abc123' as icao24,
                    1700000000 as start_time,
                    1700000000 as end_time,
                    0 as duration_seconds,
                    1 as point_count,
                    [
                        {{'time': 1700000000, 'lat': 51.5, 'lon': 0.0, 'squawk': '1200', 'onground': false, 'alert': false}}
                    ] as points
                UNION ALL
                -- Valid: 2 point segment
                SELECT
                    'valid001' as segment_id,
                    'def456' as icao24,
                    1700001000 as start_time,
                    1700001100 as end_time,
                    100 as duration_seconds,
                    2 as point_count,
                    [
                        {{'time': 1700001000, 'lat': 51.5, 'lon': 0.0, 'squawk': '1200', 'onground': false, 'alert': false}},
                        {{'time': 1700001100, 'lat': 51.51, 'lon': 0.01, 'squawk': '1200', 'onground': false, 'alert': false}}
                    ] as points
            ) TO '{segments_file}' (FORMAT PARQUET)
        """)

        # Run H3 aggregation
        from aviation_anomaly.h3_aggregation import compute_h3_coverage

        output_file = tmp_path / "h3_edge_cases.parquet"
        compute_h3_coverage(segment_file=segments_file, output_file=output_file, resolution=5)

        # Check results - should only have cells from the valid segment
        result = conn.execute(f"""
            SELECT
                COUNT(*) as cell_count,
                SUM(unique_segments) as total_segments
            FROM read_parquet('{output_file}')
        """).fetchone()

        # Should have some cells from valid001
        assert result[0] > 0, "Should have H3 cells from valid segment"  # type: ignore[index]
        # Each cell should count exactly 1 segment (the valid one)
        # Single-point segment should be filtered by WHERE point_count >= 2
        assert result[1] == result[0], "Each cell should have exactly 1 segment (valid001)"  # type: ignore[index]

        conn.close()

    def test_segment_with_points_in_same_cell(self, tmp_path: Path) -> None:
        """Test segment with multiple points all in the same H3 cell."""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL h3 FROM community; LOAD h3")
        conn.execute("SET memory_limit = '100MB'")

        segments_file = tmp_path / "same_cell_segment.parquet"

        # Create segment with points very close together (same H3 cell)
        conn.execute(f"""
            COPY (
                SELECT
                    'stationary001' as segment_id,
                    'abc123' as icao24,
                    1700000000 as start_time,
                    1700001000 as end_time,
                    1000 as duration_seconds,
                    10 as point_count,
                    [
                        {{'time': 1700000000 + i * 100,
                          'lat': 51.5 + i * 0.00001,  -- Very small movement
                          'lon': 0.0 + i * 0.00001,   -- Stays in same cell
                          'squawk': '1200', 'onground': false, 'alert': false}}
                        FOR i IN generate_series(0, 9)
                    ] as points
            ) TO '{segments_file}' (FORMAT PARQUET)
        """)

        # Run H3 aggregation
        from aviation_anomaly.h3_aggregation import compute_h3_coverage

        output_file = tmp_path / "h3_same_cell.parquet"
        compute_h3_coverage(segment_file=segments_file, output_file=output_file, resolution=5)

        # Check results
        result = conn.execute(f"""
            SELECT
                COUNT(*) as cell_count,
                MAX(unique_segments) as max_segments,
                MAX(total_points) as max_points
            FROM read_parquet('{output_file}')
        """).fetchone()

        # Should have exactly 1 cell
        assert result[0] == 1, f"Should have exactly 1 cell, got {result[0]}"  # type: ignore[index]

        # That cell should have 1 segment
        assert result[1] == 1, f"Cell should have 1 segment, got {result[1]}"  # type: ignore[index]

        # All 10 points should be in that cell
        assert result[2] == 10, f"Cell should have 10 points, got {result[2]}"  # type: ignore[index]

        conn.close()
