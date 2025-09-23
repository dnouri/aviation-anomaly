"""Tests for tile generation pipeline."""

import json
import tempfile
from pathlib import Path

import duckdb
import pytest


def test_export_h3_to_geojson_single_cell():
    """Test exporting a single H3 cell to GeoJSON format."""
    # RED: This test will fail because the function doesn't exist yet

    # Create test data with a single H3 cell
    conn = duckdb.connect()
    conn.execute("INSTALL h3; LOAD h3; INSTALL spatial; LOAD spatial")

    # Create a test H3 cell at resolution 3
    test_cell = 0x8327FFFFFFFFFFF  # Example H3 cell ID

    # Create minimal test data
    conn.execute(f"""
        CREATE TABLE test_coverage AS
        SELECT
            CAST({test_cell} AS UBIGINT) as h3_cell,
            3 as h3_res,
            1 as unique_segments,
            1 as unique_aircraft,
            100 as total_points,
            ['SEG001'] as segment_list,
            ['ABC123'] as aircraft_list
    """)

    # The function we're testing (doesn't exist yet)
    from aviation_anomaly.tile_generation import export_h3_to_geojson

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "test_r3.geojson"

        # This should fail initially (RED)
        export_h3_to_geojson(
            conn,
            coverage_table="test_coverage",
            incidents_table=None,  # No incidents for simplest case
            output_file=output_file,
        )

        # Verify the output
        assert output_file.exists()

        # Load and validate GeoJSON structure
        with open(output_file) as f:
            geojson = json.load(f)

        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 1

        feature = geojson["features"][0]
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "Polygon"
        assert len(feature["geometry"]["coordinates"]) > 0

        # Check properties
        props = feature["properties"]
        assert props["h3_cell"] == str(test_cell)
        assert props["unique_segments"] == 1
        assert props["unique_aircraft"] == 1
        assert props["total_points"] == 100


def test_export_h3_with_incidents():
    """Test exporting H3 cells with joined incident data."""
    conn = duckdb.connect()
    conn.execute("INSTALL h3; LOAD h3; INSTALL spatial; LOAD spatial")

    test_cell = 0x8327FFFFFFFFFFF

    # Create coverage data
    conn.execute(f"""
        CREATE TABLE test_coverage AS
        SELECT
            CAST({test_cell} AS UBIGINT) as h3_cell,
            3 as h3_res,
            2 as unique_segments,
            2 as unique_aircraft,
            200 as total_points,
            ['SEG001', 'SEG002'] as segment_list,
            ['ABC123', 'XYZ789'] as aircraft_list
    """)

    # Create incident data
    conn.execute(f"""
        CREATE TABLE test_incidents AS
        SELECT
            CAST({test_cell} AS UBIGINT) as h3_cell,
            3 as h3_res,
            1 as incidents_unique,
            1 as aircraft_with_incidents,
            3 as incidents_coverage,
            2 as unique_flights,
            2 as total_segments,
            ['7700'] as emergency_types_list,
            1 as emergency_type_diversity,
            '7700' as predominant_emergency_type,
            0.5 as incident_rate
    """)

    from aviation_anomaly.tile_generation import export_h3_to_geojson

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "test_r3_with_incidents.geojson"

        export_h3_to_geojson(
            conn, coverage_table="test_coverage", incidents_table="test_incidents", output_file=output_file
        )

        with open(output_file) as f:
            geojson = json.load(f)

        feature = geojson["features"][0]
        props = feature["properties"]

        # Coverage properties
        assert props["unique_segments"] == 2
        assert props["total_points"] == 200

        # Incident properties
        assert props["incidents_unique"] == 1
        assert props["incident_rate"] == 0.5
        assert props["predominant_emergency_type"] == "7700"


def test_export_coverage_without_incidents():
    """Test that cells with coverage but no incidents get NULL incident fields."""
    conn = duckdb.connect()
    conn.execute("INSTALL h3; LOAD h3; INSTALL spatial; LOAD spatial")

    # Two cells, only one has incidents
    cell_with_incidents = 0x8327FFFFFFFFFFF
    cell_without_incidents = 0x8327FFFFFFFFFFE

    # Create coverage for both cells
    conn.execute(f"""
        CREATE TABLE test_coverage AS
        SELECT * FROM (VALUES
            (CAST({cell_with_incidents} AS UBIGINT), 3, 1, 1, 100, ['SEG001'], ['ABC123']),
            (CAST({cell_without_incidents} AS UBIGINT), 3, 1, 1, 50, ['SEG002'], ['DEF456'])
        ) AS t(h3_cell, h3_res, unique_segments, unique_aircraft, total_points, segment_list, aircraft_list)
    """)

    # Create incidents for only one cell
    conn.execute(f"""
        CREATE TABLE test_incidents AS
        SELECT
            CAST({cell_with_incidents} AS UBIGINT) as h3_cell,
            3 as h3_res,
            1 as incidents_unique,
            1 as aircraft_with_incidents,
            2 as incidents_coverage,
            1 as unique_flights,
            1 as total_segments,
            ['7500'] as emergency_types_list,
            1 as emergency_type_diversity,
            '7500' as predominant_emergency_type,
            1.0 as incident_rate
    """)

    from aviation_anomaly.tile_generation import export_h3_to_geojson

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "test_partial_incidents.geojson"

        export_h3_to_geojson(
            conn, coverage_table="test_coverage", incidents_table="test_incidents", output_file=output_file
        )

        with open(output_file) as f:
            geojson = json.load(f)

        assert len(geojson["features"]) == 2

        # Find the cell without incidents
        for feature in geojson["features"]:
            if feature["properties"]["h3_cell"] == str(cell_without_incidents):
                # Should have coverage data but null incident data
                assert feature["properties"]["unique_segments"] == 1
                assert feature["properties"]["incidents_unique"] is None
                assert feature["properties"]["incident_rate"] is None
                break
        else:
            pytest.fail("Cell without incidents not found in output")
