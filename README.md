# Aviation Anomaly Tracker

[![Tests and Coverage](https://github.com/dnouri/aviation-anomaly/actions/workflows/tests-and-coverage.yml/badge.svg)](https://github.com/dnouri/aviation-anomaly/actions/workflows/tests-and-coverage.yml)
[![Coverage](https://github.com/dnouri/aviation-anomaly/raw/coverage-data/badge.svg)](https://github.com/dnouri/aviation-anomaly/tree/coverage-data)
[![Lint](https://github.com/dnouri/aviation-anomaly/actions/workflows/lint.yml/badge.svg)](https://github.com/dnouri/aviation-anomaly/actions/workflows/lint.yml)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: AGPL v3+](https://img.shields.io/badge/License-AGPL%20v3+-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

A research tool for exploring global emergency squawk patterns in historical aviation data.

**🗺️ [Explore the demo](https://anomaly.danielnouri.org/)** — Interactive map with sample week of aviation emergency data (July 2025)

## What & Why

The [OpenSky Report 2020](https://www.cs.ox.ac.uk/files/12039/OpenSky%20Report%202020.pdf) was the first systematic analysis of aircraft emergencies from ADS-B data, revealing that raw emergency squawk codes (7700/7600/7500) contain false positive rates exceeding 1000x actual emergency rates. These false positives come from brief code transitions during dial-up, ground vehicle testing, short transmission bursts, and regional ATC practice variations.

This tool makes that analysis reproducible and interactive. It processes OpenSky Network's historical ADS-B data, applies temporal, persistence, and airborne quality gates to filter spurious signals, and produces an explorable map showing where emergency patterns appear globally.

**Designed for:**
- Aviation safety researchers exploring historical patterns
- Data analysts investigating regional variations
- Incident investigators examining specific events

**Not designed for:**
- Real-time flight monitoring or operational alerting
- Safety scoring or risk assessment
- Flight tracking or surveillance

See [SPEC.md](SPEC.md) §1.1-1.2 for detailed user stories and non-goals.

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- OpenSky Network account with [data access](https://opensky-network.org/data/apply)
- 30GB+ RAM recommended for processing multi-day datasets

### Installation

```bash
git clone https://github.com/dnouri/aviation-anomaly.git
cd aviation-anomaly
uv pip install -e .
```

### Authentication

OpenSky Network credentials are required for data extraction:

```bash
export OPENSKY_USERNAME="your.email@example.com"
export OPENSKY_PASSWORD="your-password"
```

Tokens are cached for 2 hours in `.opensky_tokens.json`. For non-interactive environments (CI/CD), environment variables are required.

### Basic Workflow

1. **Extract historical data** (requires credentials, can take hours):
   ```bash
   aviation-anomaly extract --date 2025-07-01
   ```

2. **Process the data** (automated pipeline):
   ```bash
   ./scripts/process.sh
   ```
   This runs segmentation → incident detection → H3 aggregation → tile generation. Progress is logged automatically to `logs/process_TIMESTAMP.log`.

3. **Explore the results**:
   ```bash
   aviation-anomaly serve --port 8000
   ```
   Open http://localhost:8000 to view the interactive map.

## Understanding the Tool

### What It Does

The tool implements a multi-stage pipeline (see [SPEC.md](SPEC.md) §4 for technical details):

1. **Extraction** — Queries OpenSky's Trino database for historical ADS-B state vectors, caching to local Parquet files
2. **Segmentation** — Detects flight segments using gap-based splitting (20-minute gaps) with distance/duration filtering
3. **Detection** — Identifies emergency incidents using quality gates: 5+ samples over 60s, >45s persistence, airborne validation, roller-dial suppression
4. **Aggregation** — Computes H3 hexagonal cell statistics at multiple resolutions (r3-r7) with dual metrics for rates and visualization
5. **Tiles** — Generates PMTiles for web rendering via Tippecanoe

### What It Produces

- **Interactive map** showing emergency rate heatmaps with drill-down capabilities ([SPEC.md](SPEC.md) §5)
- **Parquet data files** at each pipeline stage (segments, incidents, H3 aggregates)
- **PMTiles** for efficient web visualization
- **Drill-down API** for incident-level details ([SPEC.md](SPEC.md) §6)

### Data Characteristics

ADS-B data has inherent characteristics that affect analysis:

- ~35% of records have no squawk code (normal for ADS-B networks)
- No receiver diversity information in this dataset
- Coverage varies by geographic region and time
- Velocity and altitude data not included in this dataset

These are characteristics of ADS-B networks, not data quality issues. The tool applies mitigation strategies: temporal validation strengthened to 5+ samples, conservative interpolation at 5km/30s, and coverage quality tracking. See [SPEC.md](SPEC.md) §1.4 for detailed characteristics and mitigations.

**Important:** All rates reflect *observed* traffic under OpenSky coverage, not true global rates.

## Using the Pipeline

### Data Extraction

Extraction requires OpenSky credentials and can take hours for multi-day datasets:

```bash
# Extract single day
aviation-anomaly extract --date 2025-07-01

# Extract date range (runs sequentially)
aviation-anomaly extract --date-range 2025-07-01 2025-07-07
```

Data is cached in `data/raw/` as daily Parquet files. Extraction supports resume (skips existing files) and automatic retry with exponential backoff for rate limiting. See [SPEC.md](SPEC.md) §4.1 for technical details.

### Automated Processing

Once raw data exists, use `scripts/process.sh` to run the full pipeline:

```bash
./scripts/process.sh
```

The script:
- Processes days sequentially to minimize memory usage (suitable for 30GB RAM systems)
- Skips already-completed days (incremental processing)
- Monitors memory status and detects OOM errors
- Logs all output with timestamps to `logs/process_TIMESTAMP.log`

**Note:** The script does NOT run extraction. Run `aviation-anomaly extract` first to populate `data/raw/`.

### Manual Processing

For fine-grained control, run pipeline stages individually:

```bash
# Segment flight paths
aviation-anomaly segment --date 2025-07-01

# Detect incidents (uses production filter by default)
aviation-anomaly detect --date 2025-07-01

# Aggregate to H3 grid (auto-discovers all segment files)
aviation-anomaly aggregate

# Generate tiles
aviation-anomaly tiles --pmtiles

# Start web interface
aviation-anomaly serve --port 8000
```

## Configuration

Configuration is managed via `config.toml`. Key settings:

```toml
[segments]
gap_minutes = 20            # New segment when gap > 20 minutes
min_duration_s = 600        # Filter segments < 10 minutes
min_distance_km = 30.0      # AND distance < 30km

[incidents]
debounce_minutes = 15       # Merge same-type incidents < 15min apart
default_profile = "production"  # Filter profile

[duckdb]
memory_limit = "8GB"        # Adjust based on available RAM
threads = 2                 # Parallel processing threads
```

### Filter Profiles

The system provides three filter profiles based on OpenSky Report 2020 findings ([SPEC.md](SPEC.md) §1.3):

| Profile | Purpose | False Positive Reduction |
|---------|---------|--------------------------|
| **production** (default) | Balanced for analysis | ~75% |
| **research** | Minimal filtering | ~30% |
| **high_security** | Strict validation | ~98% |

**Why filtering matters:** Analysis of real-world data shows hijack squawk (7500) rates 1,545x higher than expected. Production profile reduces false positives by ~75% while preserving legitimate incidents.

**Using profiles:**

```bash
# Default production profile
aviation-anomaly detect --date 2025-07-01

# List available profiles
aviation-anomaly detect --list-profiles

# Use specific profile
aviation-anomaly detect --date 2025-07-01 --filter-profile research
```

Quality gates applied ([SPEC.md](SPEC.md) §1.3):
- **Temporal:** 5+ samples within 60 seconds
- **Persistence:** Emergency duration >45 seconds
- **Airborne:** <30% of samples on ground
- **Confidence:** Configurable minimum score (50-80 depending on profile)

## Command Reference

### Extraction

```bash
aviation-anomaly extract --date 2025-07-01
aviation-anomaly extract --date-range 2025-07-01 2025-07-07
aviation-anomaly extract --date 2025-07-01 --output-dir data/raw --no-resume
```

### Segmentation

```bash
aviation-anomaly segment --date 2025-07-01
aviation-anomaly segment --date 2025-07-01 --output-dir data/segments
```

### Detection

```bash
aviation-anomaly detect --date 2025-07-01
aviation-anomaly detect --date 2025-07-01 --filter-profile research
aviation-anomaly detect --date 2025-07-01 --stats
```

### Aggregation

```bash
aviation-anomaly aggregate
aviation-anomaly aggregate --force
aviation-anomaly aggregate --resolutions 3,4,5,6,7
```

### Tiles

```bash
aviation-anomaly tiles --pmtiles
aviation-anomaly tiles --h3-dir data/h3 --output-dir data/tiles
```

### Server

```bash
aviation-anomaly serve --port 8000

# Access points:
# - Web UI: http://localhost:8000
# - API docs: http://localhost:8000/docs
# - Health check: http://localhost:8000/health
```

Run any command with `--help` for detailed options.

## Python API

```python
from aviation_anomaly.data_access import TrinoQueryEngine
from aviation_anomaly.extraction import extract_day
from datetime import date

# Extract a day of data (uses cached auth)
parquet_file = extract_day(date(2025, 7, 1))

# Query OpenSky directly
engine = TrinoQueryEngine()
result = engine.execute("""
    SELECT COUNT(*) as count
    FROM minio.osky.state_vectors_data4
    WHERE hour = 1751328000
""")
```

## Development

### Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=aviation_anomaly

# Run integration tests (requires credentials)
export OPENSKY_USERNAME="your.email@example.com"
export OPENSKY_PASSWORD="your-password"
uv run pytest -m integration
```

The test suite uses real production SQL via fixtures, not reimplementations. See [SPEC.md](SPEC.md) §4.5 for SQL testing methodology.

### Architecture

```
aviation_anomaly/
├── auth.py              # Token management (JWT from password flow)
├── data_access.py       # Trino query engine
├── extraction.py        # OpenSky data extraction
├── segmentation.py      # Gap-based flight segmentation
├── incident_detection.py # Quality-gated emergency detection
├── h3_aggregation.py    # Multi-resolution H3 statistics
├── tile_generation.py   # PMTiles via Tippecanoe
├── api.py               # FastAPI drill-down endpoints
├── config.py            # TOML configuration management
├── cli.py               # Click command-line interface
├── sql/                 # DuckDB SQL pipelines
└── frontend/            # MapLibre GL + vanilla JS
```

Memory-safe design: Pure SQL pipelines via DuckDB, no Pandas DataFrames, atomic writes with crash safety, per-day processing with merge for constrained environments. See [SPEC.md](SPEC.md) §4 for detailed pipeline architecture.

## Production Deployment

Deploy the application as a containerized web service with automatic HTTPS:

```bash
# Build and deploy to production server
make deploy

# Check deployment status
make deploy-status

# View container logs
make deploy-logs
```

The deployment creates:
- **Immutable container** (1.1GB) with application code and data baked in
- **Rootless Podman** runtime with systemd user service for automatic restart
- **Git-based versioning** using `${GIT_SHA}-${TIMESTAMP}` tags for rollback capability
- **Health checks** at container and application level (`/health` endpoint)

**Server requirements:**
- Podman 3.4+ for rootless container support
- Systemd with user session (lingering enabled)
- SSH access configured in Makefile (`DEPLOY_SERVER` variable)
- Reverse proxy (e.g., Caddy) for HTTPS termination (not managed by deployment automation)

**Update workflow:** Change code/data → commit → `make deploy` → automatic build, upload, and zero-downtime restart.

## Documentation

- **[SPEC.md](SPEC.md)** — Complete technical specification
  - §1: Overview, user stories, non-goals, data characteristics
  - §2-3: Functional requirements and data schemas
  - §4: ETL pipeline stages with implementation details
  - §5: Frontend visualization and UX requirements
  - §6: API specifications
  - §7-8: Testing strategy and operational considerations
- **[TODO.md](TODO.md)** — Implementation roadmap and phase tracking

## References

The [OpenSky Report 2020](https://www.cs.ox.ac.uk/files/12039/OpenSky%20Report%202020.pdf) analyzed global aircraft emergencies from ADS-B data, finding that raw squawk codes (7700/7600/7500) include many false positives from short bursts, code transitions, and ground vehicles. Regional ATC practices and receiver coverage strongly shape observed hotspots. The study applied strict filters and masking to isolate real cases.

**Implication:** Emergency squawk analysis requires robust quality gates to separate signal from noise. Maps reflect both technical artifacts and procedural differences, not just true emergencies. This tool implements those quality gates and clearly communicates coverage limitations.

## Acknowledgments

This project uses historical ADS-B data from the [OpenSky Network](https://opensky-network.org/), a crowdsourced air traffic monitoring network.

**Citation:**
Schäfer, M., Strohmeier, M., Lenders, V., Martinovic, I., & Wilhelm, M. (2014). Bringing up OpenSky: A large-scale ADS-B sensor network for research. In *Proceedings of the 13th IEEE/ACM International Symposium on Information Processing in Sensor Networks (IPSN)*, pp. 83-94. [https://ieeexplore.ieee.org/document/6846743](https://ieeexplore.ieee.org/document/6846743)

We are grateful to OpenSky Network and its volunteer contributors for making this research possible.

## License

This project is licensed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later). See [LICENSE](LICENSE) for the full license text.

The AGPL ensures that anyone who uses this software over a network (including modified versions) must provide access to the source code. This protects the research community by ensuring improvements remain open and collaborative.
