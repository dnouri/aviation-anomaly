"""Shared pytest fixtures and utilities for testing."""

import tempfile
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import duckdb
import pytest
from qck import qck


@pytest.fixture
def duckdb_conn() -> Generator[duckdb.DuckDBPyConnection]:
    """Provide a DuckDB connection with required extensions loaded.

    This fixture provides an in-memory DuckDB connection with:
    - Spatial extension for geographic functions
    - H3 extension for hexagonal grid operations

    The connection is automatically closed after the test completes.

    Example:
        def test_spatial_query(duckdb_conn):
            result = duckdb_conn.execute("SELECT ST_Point(0, 0)").fetchone()
            assert result is not None
    """
    conn = duckdb.connect(":memory:")

    # Install and load spatial extension
    try:
        conn.execute("INSTALL spatial")
        conn.execute("LOAD spatial")
    except Exception as e:
        pytest.skip(f"Spatial extension not available: {e}")

    # Install and load H3 extension from community repository
    try:
        conn.execute("INSTALL h3 FROM community")
        conn.execute("LOAD h3")
    except Exception as e:
        pytest.fail(f"H3 extension is required but not available: {e}")

    yield conn

    conn.close()


@pytest.fixture
def duckdb_conn_no_extensions() -> Generator[duckdb.DuckDBPyConnection]:
    """Provide a basic DuckDB connection without extensions.

    Use this when you need to test basic SQL functionality
    without spatial or H3 features.
    """
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def sample_flight_data(duckdb_conn: duckdb.DuckDBPyConnection) -> None:
    """Create sample flight data table for testing.

    Creates a 'flights' table with sample data including:
    - icao24: Aircraft identifier
    - time: Unix timestamp
    - lat/lon: Position
    - squawk: Transponder code
    - callsign: Flight callsign
    """
    duckdb_conn.execute("""
        CREATE TABLE flights AS
        SELECT * FROM (VALUES
            ('abc123', 1704067200, 40.7128, -74.0060, '0000', 'UAL123'),
            ('abc123', 1704067260, 40.7328, -73.9860, '0000', 'UAL123'),
            ('abc123', 1704067320, 40.7528, -73.9660, '7700', 'UAL123'),  -- Emergency
            ('def456', 1704067200, 51.5074, -0.1278, '0000', 'BAW456'),
            ('def456', 1704067260, 51.5274, -0.1078, '0000', 'BAW456'),
            ('def456', 1704068460, 51.5474, -0.0878, '0000', 'BAW456')   -- 20+ min gap
        ) AS t(icao24, time, lat, lon, squawk, callsign)
    """)


@pytest.fixture
def test_config_file(tmp_path: Path) -> Path:
    """Create a test configuration file.

    Returns:
        Path to a valid test config.toml file
    """
    config_file = tmp_path / "test_config.toml"
    config_file.write_text("""
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
    return config_file


@pytest.fixture
def sql_runner(tmp_path) -> Callable:
    """Provide a function to run SQL files or strings with Jinja2 template support.

    Returns:
        Function that runs SQL and returns results
    """

    def run_sql(
        sql: Path | str, params: dict[str, Any] | None = None, conn: duckdb.DuckDBPyConnection | None = None
    ) -> list[tuple]:
        """Run SQL from a file or string and return results.

        Args:
            sql: Path to SQL file or SQL string (can contain Jinja2 templates)
            params: Optional parameters for template substitution
            conn: Optional DuckDB connection to use (ignored, qck manages its own)

        Returns:
            Query results as list of tuples
        """
        # If it's a Path, check it exists
        if isinstance(sql, Path):
            if not sql.exists():
                raise FileNotFoundError(f"SQL file not found: {sql}")
            sql_input = str(sql)
        else:
            # For SQL strings, write to a temp file so qck can process it
            # qck expects a file path, not a SQL string directly
            temp_sql = tmp_path / f"temp_{hash(sql)}.sql"
            temp_sql.write_text(sql)
            sql_input = str(temp_sql)

        # Use qck to run the SQL with template support
        result = qck(sql_input, params=params or {})

        # Handle different result types
        if result is None:
            # DDL statements like CREATE TABLE return None
            return []
        elif hasattr(result, "fetchall"):
            return result.fetchall()
        elif hasattr(result, "df"):
            # If result is a qck ResultSet, convert DataFrame to tuples
            df = result.df()
            if df is None or df.empty:
                return []
            return [tuple(row) for row in df.itertuples(index=False)]
        else:
            return list(result) if result else []

    return run_sql


@pytest.fixture
def emergency_segment():
    """Builder fixture for creating emergency segments."""

    def _builder(
        *,
        icao24: str = "test",
        segment_id: str | None = None,
        start_time: int = 1000,
        emergency_samples: int = 10,
        emergency_span_s: int = 60,
        emergency_type: str = "7700",
        ground_ratio: float = 0.0,
        total_duration_s: int = 1000,
    ) -> dict:
        """Build a segment with emergency squawk samples."""
        if segment_id is None:
            segment_id = f"{icao24}_1"

        # Calculate time between samples
        if emergency_samples > 1:
            time_between = emergency_span_s / (emergency_samples - 1)
        else:
            time_between = 0

        # Create emergency points
        points: list[dict[str, Any]] = []
        for i in range(emergency_samples):
            points.append(
                {
                    "time": int(start_time + i * time_between),
                    "squawk": emergency_type,
                    "onground": i < (emergency_samples * ground_ratio),
                }
            )

        # Fill remaining duration with normal flight
        last_emergency_time = int(points[-1]["time"]) if points else start_time
        remaining_time = (start_time + total_duration_s) - last_emergency_time

        if remaining_time > 10:
            for t in range(int(last_emergency_time + 10), int(start_time + total_duration_s), 10):
                points.append({"time": t, "squawk": "1200", "onground": False})

        return {
            "segment_id": segment_id,
            "icao24": icao24,
            "start_time": start_time,
            "end_time": start_time + total_duration_s,
            "duration_seconds": total_duration_s,
            "point_count": len(points),
            "points": points,
        }

    return _builder


@pytest.fixture
def segment_with_roller_dial():
    """Builder fixture for segments with roller-dial pattern."""

    def _builder(*, icao24: str = "test", start_time: int = 1000) -> dict:
        """Build a segment with roller-dial pattern (77XX -> 7700)."""
        points: list[dict[str, Any]] = []

        # Roller dial sequence: pilot scrolling through codes
        for code in ["7701", "7702", "7703", "7700"]:
            for _ in range(5):
                points.append(
                    {
                        "time": start_time + len(points) * 2,
                        "squawk": code,
                        "onground": False,
                    }
                )

        # Continue with 7700 for sufficient duration
        for _ in range(30):
            points.append(
                {
                    "time": start_time + len(points) * 2,
                    "squawk": "7700",
                    "onground": False,
                }
            )

        return {
            "segment_id": f"{icao24}_1",
            "icao24": icao24,
            "start_time": start_time,
            "end_time": points[-1]["time"] if points else start_time,
            "duration_seconds": (points[-1]["time"] - start_time) if points else 0,
            "point_count": len(points),
            "points": points,
        }

    return _builder


@pytest.fixture
def normal_flight_segment():
    """Builder fixture for normal flight segments."""

    def _builder(*, icao24: str = "test", duration_s: int = 3600, start_time: int = 1000) -> dict:
        """Build a normal flight segment without emergencies."""
        points = []
        for t in range(start_time, start_time + duration_s, 10):
            points.append({"time": t, "squawk": "1200", "onground": False})

        return {
            "segment_id": f"{icao24}_1",
            "icao24": icao24,
            "start_time": start_time,
            "end_time": start_time + duration_s,
            "duration_seconds": duration_s,
            "point_count": len(points),
            "points": points,
        }

    return _builder


@pytest.fixture
def segment_with_intermittent_emergency():
    """Builder fixture for segments with intermittent emergencies."""

    def _builder(*, icao24: str = "test", bursts: list[tuple[int, int]] | None = None) -> dict:
        """Build segment with intermittent emergency bursts."""
        if bursts is None:
            # Default: 3 samples at different times (won't meet 5-in-60 rule)
            bursts = [(1000, 2), (1100, 2), (1200, 1)]

        points = []
        current_time = 1000

        for burst_time, burst_count in bursts:
            # Fill with normal flight until burst
            while current_time < burst_time:
                points.append({"time": current_time, "squawk": "1200", "onground": False})
                current_time += 10

            # Add emergency burst
            for i in range(burst_count):
                points.append({"time": burst_time + i * 2, "squawk": "7700", "onground": False})
                current_time = burst_time + i * 2 + 10

        # Fill remaining time
        end_time = current_time + 500
        while current_time < end_time:
            points.append({"time": current_time, "squawk": "1200", "onground": False})
            current_time += 10

        return {
            "segment_id": f"{icao24}_1",
            "icao24": icao24,
            "start_time": int(points[0]["time"]) if points else 1000,  # type: ignore
            "end_time": int(points[-1]["time"]) if points else 1500,  # type: ignore
            "duration_seconds": (int(points[-1]["time"]) - int(points[0]["time"])) if points else 0,  # type: ignore
            "point_count": len(points),
            "points": points,
        }

    return _builder


@pytest.fixture
def segment_with_hijack(emergency_segment):
    """Builder fixture for hijack segments."""

    def _builder(*, icao24: str = "test") -> dict:
        """Build segment with hijack emergency (7500)."""
        return emergency_segment(icao24=icao24, emergency_type="7500", emergency_samples=20, emergency_span_s=60)

    return _builder


@pytest.fixture
def segment_with_radio_failure(emergency_segment):
    """Builder fixture for radio failure segments."""

    def _builder(*, icao24: str = "test") -> dict:
        """Build segment with radio failure (7600)."""
        return emergency_segment(icao24=icao24, emergency_type="7600", emergency_samples=20, emergency_span_s=60)

    return _builder


@pytest.fixture
def run_incident_detection():
    """Fixture to run the actual SQL incident detection pipeline."""

    def _runner(segments_data: list[dict]) -> list[dict]:
        """Run the actual SQL incident detection pipeline."""
        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)

            # Create segments file
            segments_file = tmpdir / "segments.parquet"
            incidents_file = tmpdir / "incidents.parquet"

            # Write segments using DuckDB
            conn = duckdb.connect()
            conn.execute("SET memory_limit = '1GB'")

            # Build VALUES clause for segments - handle NULL squawks properly
            values = []
            for s in segments_data:
                # Convert Python None to SQL NULL in points
                points_sql = str(s["points"]).replace("None", "NULL")

                values.append(
                    f"""(
                        '{s["segment_id"]}',
                        '{s["icao24"]}',
                        {s["start_time"]},
                        {s["end_time"]},
                        {s["duration_seconds"]},
                        {s["point_count"]},
                        CAST({points_sql} AS STRUCT(
                            time INTEGER,
                            squawk VARCHAR,
                            onground BOOLEAN
                        )[])
                    )"""
                )

            conn.execute(f"""
                COPY (
                    SELECT * FROM (VALUES {",".join(values)})
                    AS t(segment_id, icao24, start_time, end_time,
                         duration_seconds, point_count, points)
                ) TO '{segments_file}' (FORMAT PARQUET)
            """)
            conn.close()

            # Run actual SQL pipeline
            sql_file = Path("aviation_anomaly/sql/incident_detection.sql")
            params = {
                "input_path": str(segments_file),
                "output_path": str(incidents_file),
                "processing_date": "2025-09-01",
                "memory_limit": "1GB",
                "threads": 2,
                "temp_directory": str(tmpdir / "duckdb_tmp"),
            }

            # Create temp directory for DuckDB
            (tmpdir / "duckdb_tmp").mkdir(exist_ok=True)

            # Execute production SQL
            qck(str(sql_file), params=params)

            # Read and return results
            conn = duckdb.connect()
            conn.execute("SET memory_limit = '1GB'")

            # Check if file was created (might have no incidents)
            if not incidents_file.exists():
                return []

            # Get column names first
            columns = conn.execute(f"""
                SELECT column_name
                FROM (DESCRIBE SELECT * FROM '{incidents_file}')
            """).fetchall()
            col_names = [c[0] for c in columns]

            # Get data
            result = conn.execute(f"SELECT * FROM '{incidents_file}'").fetchall()
            conn.close()

            # Convert to dictionaries for easier assertions
            return [dict(zip(col_names, row, strict=False)) for row in result]

    return _runner
