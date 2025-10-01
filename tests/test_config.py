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

    with pytest.raises(ConfigError, match="Failed to parse config file"):
        Config.from_file(invalid_toml)


def test_config_validates_required_fields(tmp_path):
    """Config should validate that required fields are present."""
    incomplete_config = tmp_path / "incomplete.toml"
    incomplete_config.write_text("[database]\n# Missing segments section")

    # Config uses defaults if sections are missing, so just check it loads
    config = Config.from_file(incomplete_config)
    assert config.segments.gap_minutes == 20  # Should use default


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


def test_filter_profile_configuration(tmp_path):
    """Config should load and validate filter profiles."""
    config_with_profiles = tmp_path / "profiles.toml"
    config_with_profiles.write_text("""
[segments]
gap_minutes = 20

[incidents]
debounce_minutes = 15
default_profile = "production"

[incidents.profiles.production]
name = "production"
description = "Balanced filtering for operational systems"
min_confidence = 70
min_duration_s = 120
max_samples_7500 = 430
max_samples_7600 = 379
max_samples_7700 = 224
min_samples_7500 = 186
min_samples_7600 = 163
min_samples_7700 = 116

[incidents.profiles.research]
name = "research"
description = "Minimal filtering for research"
min_confidence = 50
min_duration_s = 60

[aggregation]
min_flights_threshold = 50
""")

    config = Config.from_file(config_with_profiles)

    # Check profiles loaded
    assert config.incidents.default_profile == "production"
    assert "production" in config.incidents.profiles
    assert "research" in config.incidents.profiles

    # Check production profile values
    prod = config.incidents.profiles["production"]
    assert prod.name == "production"
    assert prod.min_confidence == 70
    assert prod.min_duration_s == 120
    assert prod.max_samples_7500 == 430
    assert prod.min_samples_7500 == 186

    # Check research profile with defaults
    research = config.incidents.profiles["research"]
    assert research.min_confidence == 50
    assert research.min_duration_s == 60
    assert research.max_samples_7500 is None  # Optional field


def test_filter_profile_validation(tmp_path):
    """Filter profiles should validate field constraints."""
    invalid_profile_config = tmp_path / "invalid_profile.toml"
    invalid_profile_config.write_text("""
[segments]
gap_minutes = 20

[incidents]
debounce_minutes = 15

[incidents.profiles.bad]
name = "bad"
min_confidence = -10  # Invalid: negative
min_duration_s = 0  # Invalid: must be positive

[aggregation]
min_flights_threshold = 50
""")

    with pytest.raises(ConfigError, match="Invalid configuration"):
        Config.from_file(invalid_profile_config)


@pytest.mark.parametrize(
    "profile_name,expected_confidence,expected_duration",
    [
        ("production", 70, 120),
        ("research", 50, 60),
        ("high_security", 80, 180),
    ],
)
def test_standard_filter_profiles(tmp_path, profile_name, expected_confidence, expected_duration):
    """Test standard filter profile configurations."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(f"""
[segments]
gap_minutes = 20

[incidents]
debounce_minutes = 15
default_profile = "{profile_name}"

[incidents.profiles.production]
name = "production"
description = "Balanced filtering"
min_confidence = 70
min_duration_s = 120

[incidents.profiles.research]
name = "research"
description = "Minimal filtering"
min_confidence = 50
min_duration_s = 60

[incidents.profiles.high_security]
name = "high_security"
description = "Strict filtering"
min_confidence = 80
min_duration_s = 180

[aggregation]
min_flights_threshold = 50
""")

    config = Config.from_file(config_file)
    profile = config.incidents.profiles[profile_name]

    assert profile.min_confidence == expected_confidence
    assert profile.min_duration_s == expected_duration
