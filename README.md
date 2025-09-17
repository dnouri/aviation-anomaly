# Aviation Anomaly Tracker

> ⚠️ **Development Status**: Active development - Phase 2 of 9 complete

Analyze emergency patterns in aviation data using OpenSky Network's historical ADS-B data.

This system detects and visualizes emergency squawk patterns (7700/7600/7500) on a global H3 hexagonal grid, providing insights into aviation incidents while acknowledging data coverage limitations.

## Features

- ✅ Query OpenSky Network's Trino database for historical ADS-B data
- ✅ Extract and cache daily flight data in Parquet format
- 🚧 Segment flight paths with gap detection and interpolation
- 🚧 Detect emergency incidents with temporal quality validation
- 🚧 Aggregate to H3 hexagonal grids with coverage metrics
- 📋 Generate PMTiles for web visualization (planned)
- 📋 Interactive map with drill-down capabilities (planned)

## Quick Start

### Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager (recommended)
- OpenSky Network account with data access

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/aviation-anomaly.git
cd aviation-anomaly

# Install with uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .
```

## Authentication

This tool requires OpenSky Network credentials to access their Trino database.

### Getting Credentials

1. Sign up at https://opensky-network.org/
2. Request data access at https://opensky-network.org/data/apply

### Setting Up Authentication

The tool supports two authentication methods:

#### 1. Environment Variables (Recommended for CI/CD)

```bash
export OPENSKY_USERNAME="your.email@example.com"
export OPENSKY_PASSWORD="your-password"
```

#### 2. Interactive Prompt

If environment variables are not set, the tool will prompt for credentials when needed.
Tokens are cached for 2 hours in `.opensky_tokens.json` in your current directory.

### How Authentication Works

- **First run**: Prompts for username/password (or uses env vars)
- **Subsequent runs**: Uses cached token (valid for 2 hours)
- **Token refresh**: Automatically refreshes expired tokens (up to 10 hours)
- **CI mode**: Requires environment variables, never prompts

## Configuration

Configuration uses TOML format in `config.toml`:

```toml
[segments]
gap_minutes = 20            # New segment when gap > 20 minutes
min_duration_s = 600        # Filter segments < 10 minutes
min_distance_km = 30.0      # AND distance < 30km

[incidents]
debounce_minutes = 15       # Merge same-type incidents < 15min apart
quality_gates.min_samples = 5           # Temporal stability
quality_gates.min_duration_s = 45       # Signal persistence
quality_gates.max_ground_ratio = 0.3    # Airborne validation

[aggregation]
min_flights_threshold = 50  # Mask cells with insufficient data
```

## Usage

### Current Capabilities

```bash
# Extract daily data (implemented)
aviation-anomaly extract --date 2025-07-01
aviation-anomaly extract --date-range 2025-07-01 2025-07-07

# With options
aviation-anomaly extract --date 2025-07-01 --output-dir data/raw --no-resume
```

### Planned Commands (Phase 3-8)

```bash
# Process flight segments (Phase 3)
aviation-anomaly segment

# Detect incidents (Phase 4)
aviation-anomaly detect

# Aggregate to H3 (Phase 5)
aviation-anomaly aggregate

# Generate tiles (Phase 6)
aviation-anomaly tiles
```

### Python API

```python
from aviation_anomaly.data_access import TrinoQueryEngine
from aviation_anomaly.extraction import extract_day
from datetime import date

# Extract a day of data (uses auth automatically)
parquet_file = extract_day(date(2025, 7, 1))

# Query OpenSky directly
engine = TrinoQueryEngine()
result = engine.execute("""
    SELECT COUNT(*) as count
    FROM minio.osky.state_vectors_data4
    WHERE hour = 1751328000  -- July 1, 2025, hour 00
""")
```

## Testing

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

## Data Characteristics

**Important**: This project works with ADS-B data which has inherent characteristics:
- ~35% of records have no squawk code (normal for ADS-B networks)
- No receiver diversity information in this dataset
- Coverage varies by geographic region and time
- See [SPEC.md](SPEC.md#14-ads-b-data-characteristics) for detailed data characteristics and mitigations

**Current Dataset**: 7 days of data (July 1-7, 2025) comprising:
- 5.1 billion position records
- 109K unique aircraft
- ~730M records per day

## Architecture

```
aviation_anomaly/
├── auth.py          # Token management and credential handling
├── data_access.py   # Trino query engine
├── extraction.py    # Data extraction and caching
├── config.py        # Configuration management
├── cli.py           # Command-line interface
└── sql/             # SQL queries for data processing
```

## Documentation

- [SPEC.md](SPEC.md) - Detailed technical specification
- [TODO.md](TODO.md) - Implementation roadmap and progress

## References

- The [OpenSky Report 2020](https://www.cs.ox.ac.uk/files/12039/OpenSky%20Report%202020.pdf) analyzed global aircraft emergencies from ADS-B data. It found that raw squawk codes (7700/7600/7500) include many false positives (short bursts, code transitions, ground vehicles) and that regional ATC practices and receiver coverage strongly shape observed hotspots. The study applied strict filters and masking to isolate real cases.

  Implication for our project: we must add robust quality gates, harmonize visibility thresholds, and clearly communicate that maps reflect both technical artefacts and procedural differences, not just true emergencies.

## License

MIT

## Contributing

Contributions are welcome! Please read our contributing guidelines before submitting PRs.
