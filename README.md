# Aviation Anomaly Tracker

Analyze emergency patterns in aviation data using OpenSky Network's historical flight data.

## Features

- Query OpenSky Network's Trino database for flight data
- Detect aviation emergencies from squawk codes
- Segment flight paths with gap detection
- Aggregate incidents to H3 hexagonal grids
- Generate PMTiles for map visualization

## Installation

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

Business logic configuration is stored in `config.toml`:

```toml
[segments]
gap_minutes = 20            # Split segments on gaps > 20 minutes
min_duration_s = 600        # Minimum segment duration
min_distance_km = 30.0      # Minimum segment distance

[incidents]
debounce_minutes = 15       # Group emergencies within 15 minutes
max_duration_cap_s = 5400   # Cap incident duration at 90 minutes

[aggregation]
min_flights_threshold = 50  # Minimum flights for analysis
```

## Usage

### Command Line Interface

```bash
# Extract monthly data
aviation-anomaly extract --year 2024 --month 1

# Process flight segments
aviation-anomaly segment

# Detect emergency incidents
aviation-anomaly detect

# Aggregate to H3 cells
aviation-anomaly aggregate

# Generate map tiles
aviation-anomaly tiles

# Start API server
aviation-anomaly serve
```

### Python API

```python
from aviation_anomaly.data_access import TrinoQueryEngine

# Create query engine (handles auth automatically)
engine = TrinoQueryEngine()

# Execute queries
result = engine.execute("""
    SELECT COUNT(*) as flights
    FROM flights_data4
    WHERE day = '2024-01-01'
""")

# Load results into DuckDB for analysis
duck_conn = engine.execute_to_duckdb("""
    SELECT * FROM flights_data4
    WHERE day = '2024-01-01'
    LIMIT 1000
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

## Architecture

```
aviation_anomaly/
├── auth.py          # Token management and credential handling
├── data_access.py   # Trino query engine
├── config.py        # Configuration management
├── cli.py           # Command-line interface
└── sql/             # SQL queries for data processing
```

## License

MIT

## Contributing

Contributions are welcome! Please read our contributing guidelines before submitting PRs.