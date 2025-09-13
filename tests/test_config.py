"""Test configuration loading and validation."""

import pytest

from aviation_anomaly.config import Config, ConfigError


def test_config_loader_fails_when_file_missing(tmp_path):
    """Config loading should fail with clear error when file doesn't exist."""
    missing_file = tmp_path / "nonexistent.toml"

    with pytest.raises(ConfigError, match="Config file not found"):
        Config.from_file(missing_file)


def test_config_loader_fails_on_invalid_toml(tmp_path):
    """Config loading should fail with clear error on invalid TOML syntax."""
    invalid_toml = tmp_path / "invalid.toml"
    invalid_toml.write_text("this is not valid toml syntax [")

    with pytest.raises(ConfigError, match="Invalid TOML"):
        Config.from_file(invalid_toml)


def test_config_validates_required_fields(tmp_path):
    """Config should validate that required fields are present."""
    incomplete_config = tmp_path / "incomplete.toml"
    incomplete_config.write_text("[database]\n# Missing segments section")

    with pytest.raises(ConfigError, match="Missing required section: segments"):
        Config.from_file(incomplete_config)


def test_config_loads_valid_configuration(tmp_path):
    """Config should load and parse valid TOML configuration."""
    valid_config = tmp_path / "config.toml"
    valid_config.write_text("""
[segments]
gap_minutes = 20
min_duration_s = 600
min_distance_km = 30

[incidents]
debounce_minutes = 15
max_duration_cap_s = 5400

[aggregation]
min_flights_threshold = 50
good_coverage_min_flights = 100
good_coverage_min_points = 4
""")

    config = Config.from_file(valid_config)

    assert config.segments.gap_minutes == 20
    assert config.segments.min_duration_s == 600
    assert config.segments.min_distance_km == 30
    assert config.incidents.debounce_minutes == 15
    assert config.aggregation.min_flights_threshold == 50


def test_config_applies_defaults_for_optional_fields(tmp_path):
    """Config should provide sensible defaults for optional fields."""
    minimal_config = tmp_path / "minimal.toml"
    minimal_config.write_text("""
[segments]
gap_minutes = 20

[incidents]
debounce_minutes = 15

[aggregation]
min_flights_threshold = 50
""")

    config = Config.from_file(minimal_config)

    # Check defaults are applied
    assert config.segments.min_duration_s == 600  # default
    assert config.segments.min_distance_km == 30  # default
    assert config.incidents.max_duration_cap_s == 5400  # default
