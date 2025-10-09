.PHONY: help install test test-unit test-integration typecheck format lint fix-whitespace check clean generate-test-data validate-sql

# Default target
.DEFAULT_GOAL := help

help: ## Show this help message
	@echo "Available commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'
	@echo ""
	@echo "Examples:"
	@echo "  make install       # Install all dependencies"
	@echo "  make test          # Run all tests in parallel"
	@echo "  make test-unit     # Run only fast unit tests"
	@echo "  make format        # Auto-format code"
	@echo "  make check         # Run all checks (fix-whitespace, format, typecheck, lint)"

install: ## Install project and dev dependencies
	@echo "Installing dependencies..."
	uv sync --dev
	@echo "Installing pre-commit hooks..."
	uv run pre-commit install
	@echo "✓ Installation complete"

test: ## Run all tests with pytest in parallel
	@echo "Running all tests..."
	PYTHONPATH=. uv run pytest tests/ -v -n auto
	@echo "✓ All tests passed"

test-unit: ## Run only unit tests (fast)
	@echo "Running unit tests..."
	PYTHONPATH=. uv run pytest tests/ -v -n auto -m "not integration"
	@echo "✓ Unit tests passed"

test-integration: ## Run only integration tests
	@echo "Running integration tests..."
	PYTHONPATH=. uv run pytest tests/ -v -m integration
	@echo "✓ Integration tests passed"

typecheck: ## Run type checking with mypy
	@echo "Running type checks..."
	uv run mypy . --exclude 'research.*' --exclude 'tmp'
	@echo "✓ Type checking passed"

format: ## Auto-format code with ruff
	@echo "Checking code formatting..."
	@uv run ruff format --check . && echo "✓ Format check passed" || (echo "⚠ Formatting needed, applying..." && uv run ruff format .)
	@echo "Checking linting..."
	@uv run ruff check . && echo "✓ Lint check passed" || (echo "⚠ Linting issues found, fixing..." && uv run ruff check --fix .)
	@echo "✓ Code formatted and checked"

lint: ## Run linting with ruff (no auto-fix)
	@echo "Linting code..."
	uv run ruff check .
	@echo "✓ Linting passed"

fix-whitespace: ## Fix trailing whitespace and missing newlines at EOF
	@echo "Fixing whitespace issues..."
	@# Remove trailing whitespace from Python files (portable sed -i usage)
	@# Exclude .venv, __pycache__, .git, and other build directories
	@find . -path ./.venv -prune -o \
		-path ./.git -prune -o \
		-path ./__pycache__ -prune -o \
		-path ./dist -prune -o \
		-path ./build -prune -o \
		-path ./.mypy_cache -prune -o \
		-path ./.ruff_cache -prune -o \
		-path ./.pytest_cache -prune -o \
		-name "*.py" -type f -print0 | xargs -0 -I {} sh -c 'sed -i.bak "s/[[:space:]]*$$//" "{}" && rm -f "{}.bak"'
	@# Add newline at end of file if missing (same exclusions)
	@find . -path ./.venv -prune -o \
		-path ./.git -prune -o \
		-path ./__pycache__ -prune -o \
		-path ./dist -prune -o \
		-path ./build -prune -o \
		-path ./.mypy_cache -prune -o \
		-path ./.ruff_cache -prune -o \
		-path ./.pytest_cache -prune -o \
		-name "*.py" -type f -print0 | xargs -0 -I {} sh -c 'tail -c1 "{}" | read -r _ || echo >> "{}"'
	@# Also fix Makefile, README, and TOML files (with exclusions)
	@for ext in md toml; do \
		find . -path ./.venv -prune -o \
			-path ./.git -prune -o \
			-name "*.$$ext" -type f -print0 | xargs -0 -I {} sh -c 'sed -i.bak "s/[[:space:]]*$$//" "{}" && rm -f "{}.bak"' ; \
		find . -path ./.venv -prune -o \
			-path ./.git -prune -o \
			-name "*.$$ext" -type f -print0 | xargs -0 -I {} sh -c 'tail -c1 "{}" | read -r _ || echo >> "{}"' ; \
	done
	@echo "✓ Whitespace fixed"

check: fix-whitespace format typecheck lint ## Run all checks (format, fix-whitespace, typecheck, lint)
	@echo "✓ All checks passed"

clean: ## Clean up generated files and caches
	@echo "Cleaning up..."
	@rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name ".coverage" -delete 2>/dev/null || true
	@echo "✓ Cleanup complete"

generate-test-data: ## Generate test data fixtures for SQL testing
	@echo "Generating test data..."
	uv run python -m aviation_anomaly.generate_test_data
	@echo "✓ Test data generated in tests/data/"

validate-sql: ## Validate SQL syntax in sql/ directory
	@echo "Validating SQL files..."
	uv run python -m aviation_anomaly.validate_sql
	@echo "✓ SQL validation complete"

# ═══════════════════════════════════════════════════════════════════════════
# PIPELINE ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════
#
# The following targets orchestrate the data processing pipeline from raw
# ADS-B data to interactive web tiles. Make handles dependency tracking and
# incremental builds automatically.
#
# QUICK START:
#   make pipeline-help        - Show pipeline-specific help
#   make pipeline-all         - Run complete pipeline
#   make pipeline-check       - Verify pipeline dependencies
#   make pipeline-clean-tiles - Remove tiles to force regeneration
#
# DEPENDENCY GRAPH:
#
#   Raw ADS-B Data (data/raw/states_YYYY-MM-DD.parquet)
#       ↓
#   Flight Segments (data/segments/segments_YYYY-MM-DD.parquet)
#       ↓  depends on: segment_pipeline.sql, config.toml
#   Incident Detection (data/incidents/incidents_YYYY-MM-DD.parquet)
#       ↓  depends on: incident_detection.sql, config.toml
#   H3 Daily Aggregation (data/h3/daily/h3_incidents_rN_YYYY-MM-DD.parquet)
#       ↓  depends on: h3_incident_metrics.sql
#   H3 Merged (data/h3/h3_incidents_rN.parquet)
#       ↓  depends on: h3_incidents_merge.sql, all daily files
#   GeoJSON Export (data/tiles/geojsonl/h3_rN.geojsonl.gz)
#       ↓  depends on: h3_to_geojsonl.sql
#   PMTiles Web Tiles (data/tiles/pmtiles/h3_rN.pmtiles)
#       ↓  depends on: pmtiles_generation.py
#   Interactive Web Map (served via aviation-anomaly serve)
#
# WHY MAKE FOR PIPELINE?
#   - Automatic dependency tracking: delete any intermediate file, Make knows
#     what to rebuild downstream
#   - Code dependencies: changing SQL/Python triggers appropriate rebuilds
#   - Incremental builds: only regenerates what changed
#   - Parallel execution: use `make -j4 pipeline-all` for parallel processing
#   - Single source of truth: all staleness logic in one place (no scattered
#     if-statements in shell or Python)
#
# ═══════════════════════════════════════════════════════════════════════════

# ───────────────────────────────────────────────────────────────────────────
# PIPELINE CONFIGURATION
# ───────────────────────────────────────────────────────────────────────────

# Dates to process (modify this for your data range)
PIPELINE_DATES := 2025-07-02 2025-07-03 2025-07-04 2025-07-05 2025-07-06 2025-07-07

# H3 resolutions to generate (3=coarse, 7=fine)
PIPELINE_RESOLUTIONS := 3 4 5 6 7

# Directories (keep in sync with config.toml)
PIPELINE_RAW_DIR := data/raw
PIPELINE_SEGMENTS_DIR := data/segments
PIPELINE_INCIDENTS_DIR := data/incidents
PIPELINE_H3_DIR := data/h3
PIPELINE_H3_DAILY_DIR := $(PIPELINE_H3_DIR)/daily
PIPELINE_TILES_DIR := data/tiles
PIPELINE_GEOJSON_DIR := $(PIPELINE_TILES_DIR)/geojsonl
PIPELINE_PMTILES_DIR := $(PIPELINE_TILES_DIR)/pmtiles

# Code dependencies (SQL and Python that affect outputs)
PIPELINE_SQL_DIR := aviation_anomaly/sql
PIPELINE_SEGMENT_SQL := $(PIPELINE_SQL_DIR)/segment_pipeline.sql
PIPELINE_INCIDENT_SQL := $(PIPELINE_SQL_DIR)/incident_detection.sql
PIPELINE_H3_METRICS_SQL := $(PIPELINE_SQL_DIR)/h3_incident_metrics.sql
PIPELINE_H3_MERGE_SQL := $(PIPELINE_SQL_DIR)/h3_incidents_merge.sql
PIPELINE_GEOJSON_SQL := $(PIPELINE_SQL_DIR)/h3_to_geojsonl.sql
PIPELINE_PMTILES_PY := aviation_anomaly/pmtiles_generation.py

# Configuration file affects all stages
PIPELINE_CONFIG := config.toml

# CLI wrapper
PIPELINE_CLI := uv run aviation-anomaly --config $(PIPELINE_CONFIG)

# ───────────────────────────────────────────────────────────────────────────
# PHONY TARGETS (pipeline-specific)
# ───────────────────────────────────────────────────────────────────────────

.PHONY: pipeline-help pipeline-all pipeline-check pipeline-clean \
        pipeline-clean-segments pipeline-clean-incidents \
        pipeline-clean-h3 pipeline-clean-tiles \
        pipeline-segments pipeline-incidents \
        pipeline-h3-merged pipeline-geojson pipeline-pmtiles

# ═══════════════════════════════════════════════════════════════════════════
# PIPELINE HELP
# ═══════════════════════════════════════════════════════════════════════════

pipeline-help: ## Show pipeline orchestration help
	@echo "════════════════════════════════════════════════════════════════════"
	@echo "  Aviation Anomaly Pipeline - Data Processing Targets"
	@echo "════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "MAIN TARGETS:"
	@echo "  make pipeline-all         - Run complete pipeline (recommended)"
	@echo "  make pipeline-segments    - Generate flight segments from raw data"
	@echo "  make pipeline-incidents   - Detect emergency incidents from segments"
	@echo "  make pipeline-h3-merged   - Aggregate incidents to H3 cells"
	@echo "  make pipeline-geojson     - Export H3 data to GeoJSON format"
	@echo "  make pipeline-pmtiles     - Generate PMTiles for web visualization"
	@echo ""
	@echo "UTILITIES:"
	@echo "  make pipeline-check       - Verify dependencies (DuckDB, Tippecanoe)"
	@echo "  make pipeline-clean       - Remove ALL generated files"
	@echo "  make pipeline-clean-tiles - Remove only tiles (for schema changes)"
	@echo ""
	@echo "CONFIGURATION:"
	@echo "  Dates:       $(PIPELINE_DATES)"
	@echo "  Resolutions: $(PIPELINE_RESOLUTIONS)"
	@echo ""
	@echo "PARALLEL EXECUTION:"
	@echo "  make -j4 pipeline-all     - Run with 4 parallel jobs (faster)"
	@echo ""
	@echo "INCREMENTAL BUILDS:"
	@echo "  Make automatically detects changes and rebuilds only what's needed."
	@echo "  Example: Delete data/tiles/geojsonl/* to force PMTiles regeneration"
	@echo "  Example: Edit h3_to_geojsonl.sql to trigger GeoJSON + PMTiles rebuild"
	@echo ""
	@echo "LOGGING:"
	@echo "  make pipeline-all 2>&1 | tee logs/run.log"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════"

# ═══════════════════════════════════════════════════════════════════════════
# FILE LISTS (computed from configuration)
# ═══════════════════════════════════════════════════════════════════════════

# Segment files (one per date)
PIPELINE_SEGMENT_FILES := $(foreach date,$(PIPELINE_DATES),$(PIPELINE_SEGMENTS_DIR)/segments_$(date).parquet)

# Incident files (one per date)
PIPELINE_INCIDENT_FILES := $(foreach date,$(PIPELINE_DATES),$(PIPELINE_INCIDENTS_DIR)/incidents_$(date).parquet)

# H3 merged files (one per resolution) - using this as the target instead of daily
PIPELINE_H3_MERGED_FILES := $(foreach res,$(PIPELINE_RESOLUTIONS),$(PIPELINE_H3_DIR)/h3_incidents_r$(res).parquet)

# GeoJSON files (one per resolution)
PIPELINE_GEOJSON_FILES := $(foreach res,$(PIPELINE_RESOLUTIONS),$(PIPELINE_GEOJSON_DIR)/h3_r$(res).geojsonl.gz)

# PMTiles files (one per resolution)
PIPELINE_PMTILES_FILES := $(foreach res,$(PIPELINE_RESOLUTIONS),$(PIPELINE_PMTILES_DIR)/h3_r$(res).pmtiles)

# ═══════════════════════════════════════════════════════════════════════════
# TOP-LEVEL TARGETS
# ═══════════════════════════════════════════════════════════════════════════

# Build everything from raw data to web tiles
pipeline-all: $(PIPELINE_PMTILES_FILES) ## Run complete pipeline
	@echo "✓ Pipeline complete! All tiles generated."
	@echo "  Start server: $(PIPELINE_CLI) serve --port 8000"
	@echo "  View at:      http://localhost:8000"

# Convenience targets for incremental builds
pipeline-segments: $(PIPELINE_SEGMENT_FILES) ## Generate flight segments
pipeline-incidents: $(PIPELINE_INCIDENT_FILES) ## Detect incidents
pipeline-h3-merged: $(PIPELINE_H3_MERGED_FILES) ## Aggregate to H3 cells
pipeline-geojson: $(PIPELINE_GEOJSON_FILES) ## Export to GeoJSON
pipeline-pmtiles: $(PIPELINE_PMTILES_FILES) ## Generate PMTiles

# ═══════════════════════════════════════════════════════════════════════════
# PATTERN RULES: SEGMENTATION
# ═══════════════════════════════════════════════════════════════════════════
# Converts raw ADS-B position data into flight segments by grouping points
# that belong to the same flight. Segments are defined by temporal and spatial
# gaps (see config.toml for thresholds).
#
# Dependencies:
#   - Raw data file for the specific date
#   - Segmentation SQL (algorithm logic)
#   - Config file (gap thresholds, min duration, etc.)
#
# Why this matters: If you change segmentation logic or thresholds, Make will
# automatically rebuild segments AND everything downstream (incidents, H3, tiles).

$(PIPELINE_SEGMENTS_DIR)/segments_%.parquet: $(PIPELINE_RAW_DIR)/states_%.parquet $(PIPELINE_SEGMENT_SQL) $(PIPELINE_CONFIG)
	@echo "═══ Segmenting: $* ═══"
	@mkdir -p $(PIPELINE_SEGMENTS_DIR)
	$(PIPELINE_CLI) segment --date $* --output-dir $(PIPELINE_SEGMENTS_DIR)
	@echo "✓ Segments generated: $@"

# ═══════════════════════════════════════════════════════════════════════════
# PATTERN RULES: INCIDENT DETECTION
# ═══════════════════════════════════════════════════════════════════════════
# Analyzes flight segments to identify emergency squawk codes (7500, 7600, 7700)
# and applies filtering rules to reduce false positives.
#
# Dependencies:
#   - Segment file for the specific date
#   - Detection SQL (squawk code logic, filtering rules)
#   - Config file (confidence thresholds, duration limits)
#
# Why this matters: If you tune detection filters or change squawk analysis,
# Make rebuilds incidents AND downstream H3 aggregations automatically.

$(PIPELINE_INCIDENTS_DIR)/incidents_%.parquet: $(PIPELINE_SEGMENTS_DIR)/segments_%.parquet $(PIPELINE_INCIDENT_SQL) $(PIPELINE_CONFIG)
	@echo "═══ Detecting incidents: $* ═══"
	@mkdir -p $(PIPELINE_INCIDENTS_DIR)
	$(PIPELINE_CLI) detect --date $* \
		--segments-dir $(PIPELINE_SEGMENTS_DIR) \
		--output-dir $(PIPELINE_INCIDENTS_DIR) \
		--stats
	@echo "✓ Incidents detected: $@"

# ═══════════════════════════════════════════════════════════════════════════
# PATTERN RULES: H3 AGGREGATION
# ═══════════════════════════════════════════════════════════════════════════
# Aggregates incidents and segments to H3 hexagonal cells. The CLI handles both
# daily aggregation and merging internally, so we model the merged file as the
# target that depends on ALL incident and segment files.
#
# Dependencies:
#   - ALL incident files (across all dates)
#   - ALL segment files (for coverage metrics)
#   - H3 aggregation SQL (both daily metrics and merge logic)
#
# Why this matters: Adding a new date triggers re-aggregation. Changing H3 SQL
# (e.g., adding type-specific counters) triggers rebuild of H3 AND tiles.
#
# Note: The CLI runs the full aggregation (daily + merge) as one command. This
# is less granular than ideal, but matches current CLI design. Future: could
# split into separate daily and merge commands for better incrementalism.

$(PIPELINE_H3_DIR)/h3_incidents_r%.parquet: $(PIPELINE_INCIDENT_FILES) $(PIPELINE_SEGMENT_FILES) $(PIPELINE_H3_METRICS_SQL) $(PIPELINE_H3_MERGE_SQL)
	@echo "═══ H3 aggregation: resolution $* ═══"
	@mkdir -p $(PIPELINE_H3_DIR)
	$(PIPELINE_CLI) aggregate --output-dir $(PIPELINE_H3_DIR) --resolutions $* --force
	@echo "✓ H3 aggregation complete: $@"

# ═══════════════════════════════════════════════════════════════════════════
# PATTERN RULES: GEOJSON EXPORT
# ═══════════════════════════════════════════════════════════════════════════
# Exports H3 aggregated data to GeoJSONL format (newline-delimited GeoJSON).
# This is an intermediate format used by Tippecanoe for PMTiles generation.
#
# Dependencies:
#   - Merged H3 file for this resolution
#   - GeoJSON export SQL (field selection, geometry conversion)
#
# Why this matters: If you add new fields to H3 data (e.g., incidents_7500)
# or change the export schema, Make automatically regenerates GeoJSON AND
# downstream PMTiles.

$(PIPELINE_GEOJSON_DIR)/h3_r%.geojsonl.gz: $(PIPELINE_H3_DIR)/h3_incidents_r%.parquet $(PIPELINE_GEOJSON_SQL)
	@echo "═══ Exporting GeoJSON: resolution $* ═══"
	@mkdir -p $(PIPELINE_GEOJSON_DIR)
	$(PIPELINE_CLI) tiles --h3-dir $(PIPELINE_H3_DIR) --output-dir $(PIPELINE_TILES_DIR) --resolutions $*
	@echo "✓ GeoJSON exported: $@"

# ═══════════════════════════════════════════════════════════════════════════
# PATTERN RULES: PMTILES GENERATION
# ═══════════════════════════════════════════════════════════════════════════
# Generates PMTiles (Protomaps tile format) from GeoJSONL using Tippecanoe.
# PMTiles are served directly to the web map for interactive visualization.
#
# Dependencies:
#   - GeoJSONL file for this resolution
#   - PMTiles generation Python code (attribute preservation logic)
#
# Why this matters: If you change which attributes to preserve in PMTiles
# (e.g., adding type-specific incident fields to the preserve list), Make
# knows to regenerate PMTiles.

$(PIPELINE_PMTILES_DIR)/h3_r%.pmtiles: $(PIPELINE_GEOJSON_DIR)/h3_r%.geojsonl.gz $(PIPELINE_PMTILES_PY)
	@echo "═══ Generating PMTiles: resolution $* ═══"
	@mkdir -p $(PIPELINE_PMTILES_DIR)
	$(PIPELINE_CLI) tiles --h3-dir $(PIPELINE_H3_DIR) --output-dir $(PIPELINE_TILES_DIR) --skip-geojson --pmtiles --resolutions $*
	@echo "✓ PMTiles generated: $@"

# ═══════════════════════════════════════════════════════════════════════════
# UTILITY TARGETS
# ═══════════════════════════════════════════════════════════════════════════

# Verify all required tools are installed
pipeline-check: ## Verify pipeline dependencies (DuckDB, Tippecanoe, etc.)
	@echo "Checking pipeline dependencies..."
	@command -v uv >/dev/null 2>&1 || (echo "✗ uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" && exit 1)
	@command -v duckdb >/dev/null 2>&1 || (echo "✗ DuckDB not found. Install: brew install duckdb (or see docs)" && exit 1)
	@command -v tippecanoe >/dev/null 2>&1 || (echo "✗ Tippecanoe not found. Install: brew install tippecanoe (or build from source)" && exit 1)
	@$(PIPELINE_CLI) --version >/dev/null 2>&1 || (echo "✗ aviation-anomaly CLI not working. Run: uv sync" && exit 1)
	@echo "✓ All pipeline dependencies installed"

# Remove all generated files (use with caution!)
# SAFETY: This does NOT delete raw data files (data/raw/*.parquet).
# Raw data is precious and irreplaceable. Only generated/derived files are deleted.
pipeline-clean: ## Remove all pipeline-generated files
	@echo "Removing all pipeline-generated files..."
	@echo "⚠️  Note: Raw data (data/raw/) is PRESERVED - only derived files deleted"
	@rm -rf $(PIPELINE_SEGMENTS_DIR)/*.parquet
	@rm -rf $(PIPELINE_INCIDENTS_DIR)/*.parquet
	@rm -rf $(PIPELINE_H3_DIR)/*.parquet
	@rm -rf $(PIPELINE_H3_DAILY_DIR)/*.parquet
	@rm -rf $(PIPELINE_GEOJSON_DIR)/*.geojsonl.gz
	@rm -rf $(PIPELINE_PMTILES_DIR)/*.pmtiles
	@echo "✓ Pipeline clean complete (raw data preserved)"

# Remove only segment files (useful for reprocessing with different thresholds)
pipeline-clean-segments: ## Remove segments (triggers rebuild of downstream)
	@echo "Removing segment files..."
	@rm -rf $(PIPELINE_SEGMENTS_DIR)/*.parquet
	@echo "✓ Segments removed (will trigger rebuild of incidents, H3, tiles)"

# Remove only incident files (useful for reprocessing with different filters)
pipeline-clean-incidents: ## Remove incidents (triggers rebuild of H3 and tiles)
	@echo "Removing incident files..."
	@rm -rf $(PIPELINE_INCIDENTS_DIR)/*.parquet
	@echo "✓ Incidents removed (will trigger rebuild of H3, tiles)"

# Remove only H3 aggregations (useful after H3 SQL changes)
pipeline-clean-h3: ## Remove H3 aggregations (triggers tile rebuild)
	@echo "Removing H3 aggregations..."
	@rm -rf $(PIPELINE_H3_DIR)/*.parquet
	@rm -rf $(PIPELINE_H3_DAILY_DIR)/*.parquet
	@echo "✓ H3 removed (will trigger rebuild of tiles)"

# Remove only tiles (useful after schema/export changes)
pipeline-clean-tiles: ## Remove tiles (GeoJSON and PMTiles)
	@echo "Removing tiles..."
	@rm -rf $(PIPELINE_GEOJSON_DIR)/*.geojsonl.gz
	@rm -rf $(PIPELINE_PMTILES_DIR)/*.pmtiles
	@echo "✓ Tiles removed (GeoJSON and PMTiles)"

# ═══════════════════════════════════════════════════════════════════════════
# DEPLOYMENT AUTOMATION
# ═══════════════════════════════════════════════════════════════════════════
#
# Container deployment workflow to production server. Handles building,
# uploading, and deploying containerized application with zero-downtime updates.
#
# QUICK START:
#   make deploy              - Build and deploy to production
#   make deploy-logs         - View container logs on server
#   make install-service     - Install systemd service (one-time setup)
#
# ARCHITECTURE:
#   - Immutable containers: Data baked into image (695MB deployment)
#   - Rootless Podman: Runs as user daniel, no root privileges required
#   - Systemd user service: Automatic restart, survives reboots
#   - Health checks: Container monitors app health, systemd restarts on failure
#   - Git-based versioning: Each build tagged with commit SHA + timestamp
#
# DEPLOYMENT FLOW:
#   1. Build container with git SHA tag (1.17GB image)
#   2. Save to tarball (~650MB compressed)
#   3. Upload to server via SCP
#   4. Load image on server
#   5. Stop old container, start new one
#   6. Tag as :production for systemd to reference
#
# ═══════════════════════════════════════════════════════════════════════════

# ───────────────────────────────────────────────────────────────────────────
# DEPLOYMENT CONFIGURATION
# ───────────────────────────────────────────────────────────────────────────

DEPLOY_SERVER := daniel@nv-network
DEPLOY_DIR := ~/aviation-anomaly-deploy
DEPLOY_IMAGE_NAME := aviation-anomaly
DEPLOY_CONTAINER_NAME := aviation-anomaly
DEPLOY_GIT_SHA := $(shell git rev-parse --short HEAD)
DEPLOY_TIMESTAMP := $(shell date +%Y%m%d)
DEPLOY_TAG := $(DEPLOY_GIT_SHA)-$(DEPLOY_TIMESTAMP)
DEPLOY_TARBALL := $(DEPLOY_IMAGE_NAME)-$(DEPLOY_TAG).tar

# ───────────────────────────────────────────────────────────────────────────
# PHONY TARGETS (deployment-specific)
# ───────────────────────────────────────────────────────────────────────────

.PHONY: deploy build-container upload-container deploy-container \
        install-service deploy-logs deploy-status

# ═══════════════════════════════════════════════════════════════════════════
# MAIN DEPLOYMENT TARGETS
# ═══════════════════════════════════════════════════════════════════════════

deploy: build-container upload-container deploy-container ## Build and deploy to production
	@echo "════════════════════════════════════════════════════════════"
	@echo "✓ Deployment complete!"
	@echo "  Version:  $(DEPLOY_TAG)"
	@echo "  Server:   $(DEPLOY_SERVER)"
	@echo "  Check:    make deploy-status"
	@echo "  Logs:     make deploy-logs"
	@echo "════════════════════════════════════════════════════════════"

build-container: ## Build container image with git-based tag
	@echo "════════════════════════════════════════════════════════════"
	@echo "Building container: $(DEPLOY_IMAGE_NAME):$(DEPLOY_TAG)"
	@echo "════════════════════════════════════════════════════════════"
	podman build --format docker -t $(DEPLOY_IMAGE_NAME):$(DEPLOY_TAG) -f Containerfile .
	podman tag $(DEPLOY_IMAGE_NAME):$(DEPLOY_TAG) $(DEPLOY_IMAGE_NAME):latest
	@echo ""
	@echo "Saving to tarball: $(DEPLOY_TARBALL)"
	podman save -o $(DEPLOY_TARBALL) $(DEPLOY_IMAGE_NAME):$(DEPLOY_TAG)
	@echo ""
	@echo "✓ Build complete"
	@echo "  Image:    $(DEPLOY_IMAGE_NAME):$(DEPLOY_TAG)"
	@printf "  Tarball:  %s (%s)\n" "$(DEPLOY_TARBALL)" "$$(du -h $(DEPLOY_TARBALL) | cut -f1)"
	@echo "  SHA:      $(DEPLOY_GIT_SHA)"

upload-container: ## Upload container tarball to server and load it
	@echo "════════════════════════════════════════════════════════════"
	@echo "Uploading: $(DEPLOY_TARBALL) → $(DEPLOY_SERVER)"
	@echo "════════════════════════════════════════════════════════════"
	@if [ ! -f "$(DEPLOY_TARBALL)" ]; then \
		echo "✗ Error: $(DEPLOY_TARBALL) not found. Run 'make build-container' first."; \
		exit 1; \
	fi
	scp $(DEPLOY_TARBALL) $(DEPLOY_SERVER):$(DEPLOY_DIR)/
	@echo ""
	@echo "Loading image on server..."
	ssh $(DEPLOY_SERVER) "podman load -i $(DEPLOY_DIR)/$(DEPLOY_TARBALL)"
	@echo ""
	@echo "✓ Upload complete"
	@echo "  Loaded:   $(DEPLOY_IMAGE_NAME):$(DEPLOY_TAG)"

deploy-container: ## Deploy container on server (stop old, start new)
	@echo "════════════════════════════════════════════════════════════"
	@echo "Deploying: $(DEPLOY_IMAGE_NAME):$(DEPLOY_TAG)"
	@echo "════════════════════════════════════════════════════════════"
	@echo "Stopping existing container (if running)..."
	ssh $(DEPLOY_SERVER) "podman stop $(DEPLOY_CONTAINER_NAME) || true"
	ssh $(DEPLOY_SERVER) "podman rm $(DEPLOY_CONTAINER_NAME) || true"
	@echo ""
	@echo "Tagging as :production for systemd..."
	ssh $(DEPLOY_SERVER) "podman tag $(DEPLOY_IMAGE_NAME):$(DEPLOY_TAG) $(DEPLOY_IMAGE_NAME):production"
	@echo ""
	@echo "Starting new container..."
	ssh $(DEPLOY_SERVER) "podman run -d --name $(DEPLOY_CONTAINER_NAME) -p 127.0.0.1:8000:8000 $(DEPLOY_IMAGE_NAME):production"
	@echo ""
	@echo "Waiting for health check..."
	@sleep 5
	@ssh $(DEPLOY_SERVER) "podman exec $(DEPLOY_CONTAINER_NAME) curl -f http://localhost:8000/health" || \
		(echo "✗ Health check failed!" && exit 1)
	@echo ""
	@echo "✓ Deployment successful"
	@echo "  Container: $(DEPLOY_CONTAINER_NAME)"
	@echo "  Version:   $(DEPLOY_TAG)"
	@echo "  Health:    OK"

install-service: ## Install systemd user service (one-time setup)
	@echo "════════════════════════════════════════════════════════════"
	@echo "Installing systemd service: aviation-anomaly.service"
	@echo "════════════════════════════════════════════════════════════"
	@echo "Copying service file to server..."
	scp deployment/aviation-anomaly.service $(DEPLOY_SERVER):~/.config/systemd/user/
	@echo ""
	@echo "Reloading systemd daemon..."
	ssh $(DEPLOY_SERVER) "systemctl --user daemon-reload"
	@echo ""
	@echo "✓ Service installed"
	@echo "  Enable:  ssh $(DEPLOY_SERVER) 'systemctl --user enable aviation-anomaly'"
	@echo "  Start:   ssh $(DEPLOY_SERVER) 'systemctl --user start aviation-anomaly'"
	@echo "  Status:  make deploy-status"

# ═══════════════════════════════════════════════════════════════════════════
# MONITORING AND UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

deploy-status: ## Check deployment status on server
	@echo "════════════════════════════════════════════════════════════"
	@echo "Deployment Status"
	@echo "════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Container status:"
	@ssh $(DEPLOY_SERVER) "podman ps -a --filter name=$(DEPLOY_CONTAINER_NAME)" || true
	@echo ""
	@echo "Systemd service status:"
	@ssh $(DEPLOY_SERVER) "systemctl --user status aviation-anomaly --no-pager" || true
	@echo ""
	@echo "Recent images:"
	@ssh $(DEPLOY_SERVER) "podman images $(DEPLOY_IMAGE_NAME) --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.Created}}'" || true

deploy-logs: ## View container logs on server (follow mode)
	@echo "Viewing logs from $(DEPLOY_SERVER):$(DEPLOY_CONTAINER_NAME)"
	@echo "Press Ctrl+C to exit"
	@echo "════════════════════════════════════════════════════════════"
	ssh $(DEPLOY_SERVER) "podman logs -f $(DEPLOY_CONTAINER_NAME)"
