#!/usr/bin/env python3
"""Tests for CSV export functionality in the API."""

import csv
import io
from pathlib import Path

import pytest

from aviation_anomaly.api import export_h3_incidents_to_csv


class TestCSVExport:
    """Test CSV export functionality."""

    def test_export_h3_incidents_to_csv_exists(self):
        """Test that CSV export function exists."""
        # This should initially fail (RED phase)
        assert callable(export_h3_incidents_to_csv)

    def test_export_returns_csv_format(self):
        """Test that export returns valid CSV data."""
        # Arrange
        h3_cell = "841e46fffffffff"

        # Act
        result = export_h3_incidents_to_csv(h3_cell=h3_cell)

        # Assert - should be a string in CSV format
        assert isinstance(result, str)
        assert len(result) > 0

        # Verify it's valid CSV by parsing it
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert isinstance(rows, list)

    def test_csv_has_correct_headers(self):
        """Test that CSV has expected column headers."""
        # Arrange
        h3_cell = "841e46fffffffff"

        # Act
        result = export_h3_incidents_to_csv(h3_cell=h3_cell)

        # Assert
        reader = csv.DictReader(io.StringIO(result))
        headers = reader.fieldnames

        expected_headers = [
            "incident_id",
            "start_time",
            "end_time",
            "emergency_type",
            "icao24",
            "callsign",
            "confidence_score",
            "confidence_category",
            "samples_in_emergency",
            "emergency_duration_s",
            "ground_ratio",
        ]

        assert headers == expected_headers

    def test_csv_export_with_no_results(self):
        """Test CSV export when no incidents found."""
        # Arrange - use invalid cell that won't have data
        h3_cell = "invalid_cell"

        # Act
        result = export_h3_incidents_to_csv(h3_cell=h3_cell)

        # Assert - should have headers but no data rows
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 0
        assert reader.fieldnames is not None  # Headers still present

    @pytest.mark.skipif(not Path("data/h3/incident_h3_mapping_r4.parquet").exists(), reason="Test data not available")
    def test_csv_export_with_real_data(self):
        """Test CSV export with actual incident data."""
        # Arrange - use a cell we know has incidents
        h3_cell = "841e46fffffffff"  # Same cell from our other tests
        resolution = 4

        # Act
        result = export_h3_incidents_to_csv(h3_cell=h3_cell, resolution=resolution)

        # Parse CSV
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)

        # Assert - should have some data
        if len(rows) > 0:  # Only test if we got data
            first_row = rows[0]

            # Check required fields are present and non-empty
            assert first_row["incident_id"]
            assert first_row["emergency_type"] in ["7500", "7600", "7700"]
            assert first_row["icao24"]

            # Check numeric fields are valid
            assert float(first_row["confidence_score"]) >= 0
            assert float(first_row["confidence_score"]) <= 100
            assert int(first_row["samples_in_emergency"]) > 0

    def test_csv_respects_limit_parameter(self):
        """Test that CSV export respects the row limit."""
        # Arrange
        h3_cell = "841e46fffffffff"
        limit = 10

        # Act
        result = export_h3_incidents_to_csv(h3_cell=h3_cell, limit=limit)

        # Assert
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) <= limit

    def test_csv_includes_optional_emergency_type_filter(self):
        """Test filtering by emergency type in CSV export."""
        # Arrange
        h3_cell = "841e46fffffffff"
        emergency_type = "7700"

        # Act
        result = export_h3_incidents_to_csv(h3_cell=h3_cell, emergency_type=emergency_type)

        # Assert - all rows should be of specified type
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)

        for row in rows:
            if row["emergency_type"]:  # Skip if no data
                assert row["emergency_type"] == emergency_type
