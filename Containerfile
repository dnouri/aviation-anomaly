# Aviation Anomaly Tracker - Container Image
# Self-contained deployment with Python 3.13, application code, and data

FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system dependencies
# - curl: for container health checks
# - ca-certificates: for HTTPS connections (DuckDB, external APIs)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv for Python dependency management
RUN pip install --no-cache-dir uv==0.4.30

# Copy project files
COPY pyproject.toml README.md config.toml ./
COPY aviation_anomaly/ ./aviation_anomaly/
COPY static/ ./static/

# Copy data files (H3, incidents, PMTiles - NOT segments)
COPY data/h3/ ./data/h3/
COPY data/incidents/ ./data/incidents/
COPY data/tiles/pmtiles/ ./data/tiles/pmtiles/

# Install Python dependencies
# Use uv to install from pyproject.toml without creating a virtualenv
# (we're in a container, no need for isolation)
RUN uv pip install --system --no-cache -e .

# Expose application port
EXPOSE 8000

# Health check: verify API is responding and healthy
# Runs every 30 seconds, 3 second timeout, 3 retries before marking unhealthy
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run FastAPI application with uvicorn
# --host 0.0.0.0: bind to all interfaces (required for container networking)
# --port 8000: application port
# --workers 1: single worker (can increase based on CPU cores if needed)
CMD ["uvicorn", "aviation_anomaly.api:app", "--host", "0.0.0.0", "--port", "8000"]
