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
