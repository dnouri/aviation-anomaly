"""Test CLI extract command."""

import datetime
from unittest.mock import Mock, patch

from click.testing import CliRunner

from aviation_anomaly.cli import extract


def test_extract_command_with_valid_date(tmp_path):
    """Test extract command with valid date."""
    runner = CliRunner()

    # Mock the extract_day function to avoid actual API calls
    mock_output_file = tmp_path / "states_2025-01-01.parquet"
    mock_output_file.write_text("")  # Create empty file

    with patch("aviation_anomaly.extraction.extract_day") as mock_extract:
        mock_extract.return_value = mock_output_file

        # Mock duckdb to return row count
        with patch("duckdb.connect") as mock_connect:
            mock_conn = Mock()
            mock_conn.execute.return_value.fetchone.return_value = (1000,)
            mock_connect.return_value = mock_conn

            result = runner.invoke(extract, ["--date", "2025-01-01", "--output-dir", str(tmp_path)])

            assert result.exit_code == 0
            assert "Extracting data for 2025-01-01" in result.output
            assert "✓ Extraction complete" in result.output
            assert "Rows: 1,000" in result.output

            # Verify extract_day was called with correct arguments
            mock_extract.assert_called_once_with(datetime.date(2025, 1, 1), tmp_path)


def test_extract_command_with_invalid_date():
    """Test extract command with invalid future date."""
    runner = CliRunner()

    with patch("aviation_anomaly.extraction.extract_day") as mock_extract:
        mock_extract.side_effect = ValueError("Cannot extract future date: 2030-01-01")

        result = runner.invoke(extract, ["--date", "2030-01-01"])

        # Without try/except, Click shows the exception
        assert result.exit_code != 0
        assert result.exception is not None
        assert "Cannot extract future date: 2030-01-01" in str(result.exception)


def test_extract_command_missing_date():
    """Test extract command without required date."""
    runner = CliRunner()

    result = runner.invoke(extract, [])

    assert result.exit_code != 0
    assert "Error: Provide either --date or both --from-date and --to-date" in result.output


def test_extract_command_with_date_range(tmp_path):
    """Test extract command with date range."""
    runner = CliRunner()

    # Mock the extract_date_range function
    mock_files = [
        tmp_path / "states_2025-01-01.parquet",
        tmp_path / "states_2025-01-02.parquet",
    ]
    for f in mock_files:
        f.write_text("")  # Create empty files

    with patch("aviation_anomaly.extraction.extract_date_range") as mock_extract:
        mock_extract.return_value = mock_files

        result = runner.invoke(
            extract, ["--from-date", "2025-01-01", "--to-date", "2025-01-02", "--output-dir", str(tmp_path)]
        )

        assert result.exit_code == 0
        assert "Extracting data from 2025-01-01 to 2025-01-02" in result.output
        assert "✓ Extracted 2 files" in result.output

        # Verify extract_date_range was called correctly
        mock_extract.assert_called_once_with(datetime.date(2025, 1, 1), datetime.date(2025, 1, 2), tmp_path)


def test_extract_command_conflicting_options():
    """Test extract command with conflicting date options."""
    runner = CliRunner()

    result = runner.invoke(extract, ["--date", "2025-01-01", "--from-date", "2025-01-01"])

    assert result.exit_code != 0
    assert "Error: Use either --date or --from-date/--to-date, not both" in result.output
