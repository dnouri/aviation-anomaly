"""Tests for PMTiles generation with Tippecanoe."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from aviation_anomaly.pmtiles_generation import (
    build_tippecanoe_command,
    check_tippecanoe_installed,
    generate_pmtiles,
    get_zoom_range_for_resolution,
)


def test_get_zoom_range_for_resolution():
    """Test zoom range calculation based on H3 resolution."""
    # H3 resolution 3 (coarse) -> wider zoom range
    assert get_zoom_range_for_resolution(3) == (3, 7)

    # H3 resolution 5 (medium) -> medium zoom range
    assert get_zoom_range_for_resolution(5) == (5, 9)

    # H3 resolution 6 (finest) -> narrower zoom range
    assert get_zoom_range_for_resolution(6) == (6, 10)


def test_build_tippecanoe_command():
    """Test Tippecanoe command construction."""
    cmd = build_tippecanoe_command(
        input_file=Path("input.geojson"),
        output_file=Path("output.pmtiles"),
        min_zoom=3,
        max_zoom=7,
    )

    assert "tippecanoe" == cmd[0]
    assert "-o" in cmd
    assert "output.pmtiles" in cmd
    assert "--minimum-zoom=3" in cmd
    assert "--maximum-zoom=7" in cmd
    assert "input.geojson" in cmd

    # Should include feature limits to control tile size
    assert "--maximum-tile-features" in " ".join(cmd)


def test_build_tippecanoe_command_with_attributes():
    """Test command includes attribute preservation."""
    cmd = build_tippecanoe_command(
        input_file=Path("input.geojson"),
        output_file=Path("output.pmtiles"),
        min_zoom=3,
        max_zoom=7,
        preserve_attributes=["incidents_unique", "confidence_score"],
    )

    cmd_str = " ".join(cmd)
    # Should preserve specified attributes
    assert "--include incidents_unique" in cmd_str
    assert "--include confidence_score" in cmd_str


def test_check_tippecanoe_installed():
    """Test checking for Tippecanoe availability."""
    with patch("subprocess.run") as mock_run:
        # Simulate Tippecanoe installed
        mock_run.return_value = Mock(returncode=0)
        assert check_tippecanoe_installed() is True

        # Simulate Tippecanoe not installed
        mock_run.side_effect = FileNotFoundError
        assert check_tippecanoe_installed() is False


def test_generate_pmtiles_tippecanoe_not_installed(tmp_path):
    """Test graceful failure when Tippecanoe not installed."""
    input_file = tmp_path / "input.geojson"
    output_file = tmp_path / "output.pmtiles"

    # Create minimal GeoJSON
    geojson_data = {"type": "FeatureCollection", "features": []}
    with open(input_file, "w") as f:
        json.dump(geojson_data, f)

    with patch("aviation_anomaly.pmtiles_generation.check_tippecanoe_installed", return_value=False):
        with pytest.raises(RuntimeError, match="Tippecanoe is not installed"):
            generate_pmtiles(input_file, output_file, resolution=3)


def test_generate_pmtiles_success(tmp_path):
    """Test successful PMTiles generation (mocked)."""
    input_file = tmp_path / "input.geojson"
    output_file = tmp_path / "output.pmtiles"

    # Create minimal GeoJSON with one feature
    geojson_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-122, 37], [-122, 38], [-121, 38], [-121, 37], [-122, 37]]],
                },
                "properties": {"h3_cell": "832830fffffffff", "unique_segments": 10, "incidents_unique": 2},
            }
        ],
    }
    with open(input_file, "w") as f:
        json.dump(geojson_data, f)

    with patch("aviation_anomaly.pmtiles_generation.check_tippecanoe_installed", return_value=True):
        with patch("subprocess.run") as mock_run:
            # Simulate successful Tippecanoe execution
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            # Create a fake output file so stat() works
            output_file.write_bytes(b"fake pmtiles content")

            result = generate_pmtiles(input_file, output_file, resolution=3)

            assert result == output_file
            mock_run.assert_called_once()

            # Verify command includes expected parameters
            cmd = mock_run.call_args[0][0]
            assert "tippecanoe" in cmd[0]
            assert str(input_file) in cmd
            assert str(output_file) in cmd


def test_generate_pmtiles_preserves_type_specific_fields(tmp_path):
    """Test that type-specific incident counts are in the preserve list."""
    input_file = tmp_path / "input.geojsonl.gz"
    output_file = tmp_path / "output.pmtiles"

    # Create compressed GeoJSONL with type-specific fields
    import gzip

    features = [
        json.dumps(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-122, 37], [-122, 38], [-121, 38], [-121, 37], [-122, 37]]],
                },
                "properties": {
                    "h3_cell": "832830fffffffff",
                    "h3_res": 3,
                    "unique_segments": 10,
                    "incidents_unique": 5,
                    "incidents_7500": 2,
                    "incidents_7600": 1,
                    "incidents_7700": 2,
                },
            }
        )
    ]

    with gzip.open(input_file, "wt") as f:
        for feature in features:
            f.write(feature + "\n")

    with patch("aviation_anomaly.pmtiles_generation.check_tippecanoe_installed", return_value=True):
        with patch("subprocess.run") as mock_run:
            # Simulate successful execution
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
            output_file.write_bytes(b"fake pmtiles")

            generate_pmtiles(input_file, output_file, resolution=3, preserve_all_attributes=False)

            # Verify command includes type-specific fields
            cmd = mock_run.call_args[0][0]
            cmd_str = " ".join(cmd)

            assert "--include incidents_7500" in cmd_str, "Must preserve incidents_7500"
            assert "--include incidents_7600" in cmd_str, "Must preserve incidents_7600"
            assert "--include incidents_7700" in cmd_str, "Must preserve incidents_7700"


@pytest.mark.integration
@pytest.mark.skipif(
    not subprocess.run(["which", "tippecanoe"], capture_output=True).returncode == 0, reason="Tippecanoe not installed"
)
def test_generate_pmtiles_integration(tmp_path):
    """Integration test with actual Tippecanoe (if installed)."""
    input_file = tmp_path / "test.geojson"
    output_file = tmp_path / "test.pmtiles"

    # Create a minimal but valid GeoJSON
    geojson_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-122.5, 37.5], [-122.5, 37.6], [-122.4, 37.6], [-122.4, 37.5], [-122.5, 37.5]]],
                },
                "properties": {
                    "h3_cell": "8328307ffffffff",
                    "h3_res": 3,
                    "unique_segments": 100,
                    "unique_aircraft": 50,
                    "total_points": 5000,
                    "incidents_unique": 5,
                    "confidence_score": 75.5,
                },
            }
        ],
    }

    with open(input_file, "w") as f:
        json.dump(geojson_data, f)

    # Generate PMTiles
    result = generate_pmtiles(input_file, output_file, resolution=3)

    # Verify output exists and has content
    assert result.exists()
    assert result.stat().st_size > 0

    # Could add more validation here if we have PMTiles reader library
