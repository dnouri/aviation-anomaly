"""Configuration management for Aviation Anomaly Tracker."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class SegmentConfig(BaseModel):
    """Configuration for flight segment processing."""

    gap_minutes: int = Field(default=20, description="Minutes of gap to split segments")
    min_duration_s: int = Field(default=600, description="Minimum segment duration in seconds")
    min_distance_km: float = Field(default=30.0, description="Minimum segment distance in km")

    @field_validator("gap_minutes", "min_duration_s")
    @classmethod
    def validate_positive(cls, v: int) -> int:
        """Ensure values are positive."""
        if v <= 0:
            raise ValueError("Must be positive")
        return v


class IncidentConfig(BaseModel):
    """Configuration for incident detection."""

    debounce_minutes: int = Field(default=15, description="Minutes to debounce incidents")
    max_duration_cap_s: int = Field(default=5400, description="Maximum incident duration in seconds")

    @field_validator("debounce_minutes", "max_duration_cap_s")
    @classmethod
    def validate_positive(cls, v: int) -> int:
        """Ensure values are positive."""
        if v <= 0:
            raise ValueError("Must be positive")
        return v


class AggregationConfig(BaseModel):
    """Configuration for data aggregation."""

    min_flights_threshold: int = Field(default=50, description="Minimum flights for analysis")
    good_coverage_min_flights: int = Field(default=100, description="Flights for good coverage")
    good_coverage_min_points: int = Field(default=4, description="Points for good coverage")

    @field_validator("min_flights_threshold", "good_coverage_min_flights", "good_coverage_min_points")
    @classmethod
    def validate_positive(cls, v: int) -> int:
        """Ensure values are positive."""
        if v <= 0:
            raise ValueError("Must be positive")
        return v


class DuckDBConfig(BaseModel):
    """Configuration for DuckDB execution."""

    memory_limit: str = Field(default="8GB", description="Memory limit for DuckDB operations")
    threads: int = Field(default=4, description="Number of threads for parallel processing")
    temp_directory: str = Field(default="/tmp/duckdb", description="Temp directory for disk spilling")
    max_temp_directory_size: str = Field(default="100GB", description="Maximum size for temporary files")

    @field_validator("memory_limit", "max_temp_directory_size")
    @classmethod
    def validate_size_format(cls, v: str) -> str:
        """Ensure size is in valid format."""
        import re

        if not re.match(r"^\d+[KMGT]B$", v.upper()):
            raise ValueError("Size must be like '8GB' or '512MB'")
        return v.upper()

    @field_validator("threads")
    @classmethod
    def validate_positive(cls, v: int) -> int:
        """Ensure threads is positive."""
        if v <= 0:
            raise ValueError("Must be positive")
        return v


class Config(BaseModel):
    """Main configuration for Aviation Anomaly Tracker."""

    segments: SegmentConfig = Field(default_factory=SegmentConfig)
    incidents: IncidentConfig = Field(default_factory=IncidentConfig)
    aggregation: AggregationConfig = Field(default_factory=AggregationConfig)
    duckdb: DuckDBConfig = Field(default_factory=DuckDBConfig)

    @classmethod
    def from_file(cls, path: Path | str) -> "Config":
        """Load configuration from TOML file.

        Args:
            path: Path to config.toml file

        Returns:
            Config instance

        Raises:
            ConfigError: If file cannot be loaded or parsed
        """
        path = Path(path)

        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")

        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            raise ConfigError(f"Failed to parse config file: {e}") from e

        try:
            return cls(**data)
        except Exception as e:
            raise ConfigError(f"Invalid configuration: {e}") from e

    def save(self, path: Path | str) -> None:
        """Save configuration to TOML file.

        Args:
            path: Path to save config.toml file
        """
        import tomli_w

        path = Path(path)
        data = self.model_dump()

        with open(path, "wb") as f:
            tomli_w.dump(data, f)


class ConfigError(Exception):
    """Configuration error."""

    pass
