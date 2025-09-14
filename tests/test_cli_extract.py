"""Test CLI extract command."""


import pytest
from click.testing import CliRunner

from aviation_anomaly.cli import extract


class MockDuckDBConnection:
    """Mock for DuckDB connection."""
    def __init__(self, row_count=1000):
        self.row_count = row_count

    def execute(self, query):
        return self

    def fetchone(self):
        return (self.row_count,)

    def close(self):
        pass


@pytest.fixture
def mock_duckdb(monkeypatch):
    """Mock duckdb.connect to avoid database operations."""
    def mock_connect():
        return MockDuckDBConnection()

    import duckdb
    monkeypatch.setattr(duckdb, "connect", mock_connect)


def test_extract_command_with_valid_date(tmp_path, monkeypatch, mock_duckdb):
    """Test extract command with valid date."""
    runner = CliRunner()

    # Mock the extract_day function to avoid actual API calls
    mock_output_file = tmp_path / "states_2025-01-01.parquet"
    mock_output_file.write_text("")  # Create empty file

    def mock_extract_day(date, output_dir, force_redownload=False):
        return mock_output_file

    monkeypatch.setattr("aviation_anomaly.extraction.extract_day", mock_extract_day)

    result = runner.invoke(extract, ["--date", "2025-01-01", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "Extracting data for 2025-01-01" in result.output
    assert "✓ Extraction complete" in result.output
    assert "Rows: 1,000" in result.output


def test_extract_command_with_invalid_date(monkeypatch):
    """Test extract command with invalid future date."""
    runner = CliRunner()

    def mock_extract_day(date, output_dir, force_redownload=False):
        raise ValueError(f"Cannot extract future date: {date}")

    monkeypatch.setattr("aviation_anomaly.extraction.extract_day", mock_extract_day)

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


def test_extract_command_with_date_range(tmp_path, monkeypatch):
    """Test extract command with date range."""
    runner = CliRunner()

    # Mock the extract_date_range function
    mock_files = [
        tmp_path / "states_2025-01-01.parquet",
        tmp_path / "states_2025-01-02.parquet",
    ]
    for f in mock_files:
        f.write_text("")  # Create empty files

    def mock_extract_date_range(from_date, to_date, output_dir, force_redownload=False):
        return mock_files

    monkeypatch.setattr("aviation_anomaly.extraction.extract_date_range", mock_extract_date_range)

    result = runner.invoke(
        extract, ["--from-date", "2025-01-01", "--to-date", "2025-01-02", "--output-dir", str(tmp_path)]
    )

    assert result.exit_code == 0
    assert "Extracting data from 2025-01-01 to 2025-01-02" in result.output
    assert "✓ Extracted 2 files" in result.output


def test_extract_command_conflicting_options():
    """Test extract command with conflicting date options."""
    runner = CliRunner()

    result = runner.invoke(extract, ["--date", "2025-01-01", "--from-date", "2025-01-01"])

    assert result.exit_code != 0
    assert "Error: Use either --date or --from-date/--to-date, not both" in result.output


def test_extract_command_with_no_resume_flag(tmp_path, monkeypatch, mock_duckdb):
    """Test extract command with --no-resume flag."""
    runner = CliRunner()

    # Mock the extract_day function
    mock_output_file = tmp_path / "states_2025-01-01.parquet"
    mock_output_file.write_text("")  # Create empty file

    # Track calls to verify force_redownload is True
    calls = []

    def mock_extract_day(date, output_dir, force_redownload=False):
        calls.append((date, output_dir, force_redownload))
        return mock_output_file

    monkeypatch.setattr("aviation_anomaly.extraction.extract_day", mock_extract_day)

    result = runner.invoke(extract, ["--date", "2025-01-01", "--output-dir", str(tmp_path), "--no-resume"])

    assert result.exit_code == 0
    assert "Force re-download: enabled" in result.output

    # Verify extract_day was called with force_redownload=True
    assert len(calls) == 1
    assert calls[0][2] is True  # force_redownload should be True
