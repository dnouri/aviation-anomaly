"""Test FastAPI application setup and routes."""

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_create_app_returns_fastapi_instance():
    """Create app should return a FastAPI application."""
    from aviation_anomaly.api import create_app

    app = create_app()

    assert isinstance(app, FastAPI)
    assert app.title == "Aviation Anomaly Tracker API"


def test_app_has_expected_routes():
    """App should have all expected API routes."""
    from aviation_anomaly.api import create_app

    app = create_app()
    routes = {getattr(route, "path", None) for route in app.routes}
    routes = {r for r in routes if r is not None}  # Filter None values

    # Check main API routes exist
    assert "/api/h3/summary" in routes
    assert "/api/h3/incidents" in routes
    assert "/api/h3/incidents.csv" in routes

    # OpenAPI routes should exist
    assert "/openapi.json" in routes
    assert "/docs" in routes


def test_health_endpoint(tmp_path):
    """Health check endpoint should return OK."""
    from aviation_anomaly.api import create_app
    from aviation_anomaly.config import Config

    # Create test config with tmp_path as data_dir
    test_config = Config()
    test_config.data_dir = tmp_path

    # Create dummy H3 file for health check
    h3_dir = tmp_path / "h3"
    h3_dir.mkdir(parents=True, exist_ok=True)
    h3_file = h3_dir / "h3_incidents_r3.parquet"

    # Create a minimal valid parquet file
    import duckdb

    conn = duckdb.connect()
    conn.execute(f"""
        COPY (
            SELECT
                123456789::UBIGINT as h3_cell,
                3 as h3_res
        ) TO '{h3_file}' (FORMAT PARQUET)
    """)
    conn.close()

    app = create_app(test_config)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] == "healthy"
    assert "checks" in response_json


def test_h3_summary_endpoint_validation(tmp_path):
    """H3 summary endpoint should validate parameters."""
    from aviation_anomaly.api import create_app
    from aviation_anomaly.config import Config

    # Create test config with tmp_path as data_dir
    test_config = Config()
    test_config.data_dir = tmp_path

    app = create_app(test_config)
    client = TestClient(app)

    # Missing required parameter
    response = client.get("/api/h3/summary")
    assert response.status_code == 422  # Unprocessable Entity

    # Invalid resolution
    response = client.get("/api/h3/summary?h3_cell=123&resolution=10")
    assert response.status_code == 422


def test_h3_incidents_endpoint_returns_data(tmp_path):
    """H3 incidents endpoint should return expected format."""
    from aviation_anomaly.api import create_app
    from aviation_anomaly.config import Config

    # Create test config with tmp_path as data_dir
    test_config = Config()
    test_config.data_dir = tmp_path

    app = create_app(test_config)
    client = TestClient(app)

    # Valid request (will return empty if no data)
    response = client.get("/api/h3/incidents?h3_cell=123456789&resolution=5")

    assert response.status_code == 200
    data = response.json()
    assert "meta" in data
    assert "rows" in data
    assert isinstance(data["rows"], list)


def test_csv_export_endpoint(tmp_path):
    """CSV export endpoint should return CSV content."""
    from aviation_anomaly.api import create_app
    from aviation_anomaly.config import Config

    # Create test config with tmp_path as data_dir
    test_config = Config()
    test_config.data_dir = tmp_path

    app = create_app(test_config)
    client = TestClient(app)

    response = client.get("/api/h3/incidents.csv?h3_cell=123456789&resolution=5")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"

    # Should have CSV header even if no data
    content = response.text
    assert "incident_id" in content
    assert "emergency_type" in content
