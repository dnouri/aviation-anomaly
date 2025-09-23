"""Test Click CLI structure."""

import click
from click.testing import CliRunner

from aviation_anomaly.cli import main


def test_cli_entry_point_exists():
    """CLI entry point should exist and be callable."""
    assert main is not None
    assert callable(main)


def test_cli_help_command():
    """CLI should respond to --help with usage information."""
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "Aviation Anomaly Tracker" in result.output
    assert "Options:" in result.output
    assert "Commands:" in result.output


def test_cli_version_option():
    """CLI should show version with --version."""
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])

    assert result.exit_code == 0
    assert "0.1.0" in result.output  # Version from pyproject.toml


def test_cli_config_option(test_config_file):
    """CLI should accept --config option."""
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(test_config_file), "--help"])

    assert result.exit_code == 0


def test_cli_without_config_uses_default():
    """CLI should work without explicit config file."""
    runner = CliRunner()
    # Just test that it doesn't crash when no config specified
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0


def test_cli_invalid_config_shows_error(tmp_path):
    """CLI should show clear error for invalid config."""
    bad_config = tmp_path / "bad.toml"
    bad_config.write_text("invalid toml [")

    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(bad_config)])

    # Should fail but not crash
    assert result.exit_code != 0
    assert "Invalid TOML" in result.output or "error" in result.output.lower()


def test_cli_groups_exist():
    """CLI should have expected command groups."""
    # Get the Click context
    assert isinstance(main, click.Group) or isinstance(main, click.Command)

    if isinstance(main, click.Group):
        # Check for expected commands (we'll add these later)
        command_names = main.list_commands(click.Context(main))
        # For now, might be empty, but structure should exist
        assert isinstance(command_names, list)


def test_aggregate_command_with_incidents(tmp_path, test_config_file):
    """Test that aggregate command processes incidents when available."""

    import duckdb

    # Create test data directories
    segments_dir = tmp_path / "data" / "segments"
    segments_dir.mkdir(parents=True)
    incidents_dir = tmp_path / "data" / "incidents"
    incidents_dir.mkdir(parents=True)

    # Create minimal segment file
    segments_file = segments_dir / "segments_2025-07-02.parquet"
    conn = duckdb.connect()
    conn.execute(f"""
        COPY (
            SELECT
                'seg1' as segment_id,
                'abc123' as icao24,
                1751400000 as start_time,
                1751400600 as end_time,
                600 as duration_seconds,
                2 as point_count,
                [
                    {{'time': 1751400000, 'lat': 51.5, 'lon': -0.1, 'squawk': '7700'}},
                    {{'time': 1751400600, 'lat': 51.51, 'lon': -0.09, 'squawk': '7700'}}
                ] as points
        ) TO '{segments_file}' (FORMAT PARQUET)
    """)

    # Create minimal incident file
    incidents_file = incidents_dir / "incidents_2025-07-02.parquet"
    conn.execute(f"""
        COPY (
            SELECT
                'inc1' as incident_id,
                'seg1' as segment_id,
                'abc123' as icao24,
                '7700' as emergency_type,
                1751400000 as start_time,
                1751400600 as end_time,
                600 as duration_seconds,
                10 as total_samples,
                0.0 as ground_percentage,
                85 as confidence_score,
                'HIGH' as confidence_level,
                false as has_roller_dial
        ) TO '{incidents_file}' (FORMAT PARQUET)
    """)
    conn.close()

    # Run aggregate command
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        import os

        os.chdir(tmp_path)

        result = runner.invoke(
            main,
            [
                "--config",
                str(test_config_file),
                "aggregate",
                "--segment-file",
                str(segments_file),
                "--output-dir",
                str(tmp_path / "h3"),
                "--resolutions",
                "5",
            ],
        )

        # Should succeed
        assert result.exit_code == 0, f"Command failed: {result.output}"

        # Should mention processing incidents
        assert "incident" in result.output.lower(), "Should mention processing incidents"
