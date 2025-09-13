"""Configuration loading and validation."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Self


class ConfigError(Exception):
    """Configuration-related errors."""

    pass


@dataclass
class SegmentsConfig:
    """Segmentation configuration."""

    gap_minutes: int
    min_duration_s: int = 600
    min_distance_km: int = 30


@dataclass
class IncidentsConfig:
    """Incident detection configuration."""

    debounce_minutes: int
    max_duration_cap_s: int = 5400


@dataclass
class AggregationConfig:
    """Aggregation configuration."""

    min_flights_threshold: int
    good_coverage_min_flights: int = 100
    good_coverage_min_points: int = 4


@dataclass
class Config:
    """Application configuration."""

    segments: SegmentsConfig
    incidents: IncidentsConfig
    aggregation: AggregationConfig

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Load configuration from TOML file.

        Args:
            path: Path to TOML configuration file

        Returns:
            Parsed configuration object

        Raises:
            ConfigError: If file missing, invalid TOML, or missing required fields
        """
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")

        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"Invalid TOML in {path}: {e}") from e

        # Validate required sections exist
        required_sections = ["segments", "incidents", "aggregation"]
        for section in required_sections:
            if section not in data:
                raise ConfigError(f"Missing required section: {section}")

        # Parse each section with validation
        segments = cls._parse_segments(data["segments"])
        incidents = cls._parse_incidents(data["incidents"])
        aggregation = cls._parse_aggregation(data["aggregation"])

        return cls(
            segments=segments,
            incidents=incidents,
            aggregation=aggregation,
        )

    @staticmethod
    def _parse_segments(data: dict) -> SegmentsConfig:
        """Parse and validate segments configuration."""
        if "gap_minutes" not in data:
            raise ConfigError("Missing required field: segments.gap_minutes")

        return SegmentsConfig(
            gap_minutes=data["gap_minutes"],
            min_duration_s=data.get("min_duration_s", 600),
            min_distance_km=data.get("min_distance_km", 30),
        )

    @staticmethod
    def _parse_incidents(data: dict) -> IncidentsConfig:
        """Parse and validate incidents configuration."""
        if "debounce_minutes" not in data:
            raise ConfigError("Missing required field: incidents.debounce_minutes")

        return IncidentsConfig(
            debounce_minutes=data["debounce_minutes"],
            max_duration_cap_s=data.get("max_duration_cap_s", 5400),
        )

    @staticmethod
    def _parse_aggregation(data: dict) -> AggregationConfig:
        """Parse and validate aggregation configuration."""
        if "min_flights_threshold" not in data:
            raise ConfigError("Missing required field: aggregation.min_flights_threshold")

        return AggregationConfig(
            min_flights_threshold=data["min_flights_threshold"],
            good_coverage_min_flights=data.get("good_coverage_min_flights", 100),
            good_coverage_min_points=data.get("good_coverage_min_points", 4),
        )
