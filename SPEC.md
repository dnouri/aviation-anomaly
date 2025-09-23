# Aviation Anomaly Tracker — Detailed Specification

> Status: **Draft for Dev Handoff**
> Scope: **Global but shallow** (7-day prototype; Phase‑1 map validated at H3 r4, with r3–r7 prepared)
> Data Available: **7 days** (July 1-7, 2025) - 5.1 billion records, 109K unique aircraft
> Decision Log: See §1.3

---

## 1. Overview & Vision

This document defines the end‑to‑end system that ingests OpenSky state vectors, detects emergency-squawk incidents (7500/7600/7700), aggregates them onto an H3 grid, and renders a performant, drill‑able global hotspot map. The intent is **exploratory analysis**, not operational alerting or safety scoring. All rates reflect **observed** traffic under OpenSky coverage.

### 1.1 User Stories

- **Analyst** — View a global heatmap of emergency **rates** per hex; filter by month and squawk type; click to inspect counts and context.
- **Investigator** — Click a hotspot to list included incidents with timestamp, squawk, callsign, registration, and aircraft type.
- **Developer** — Run reproducible ETL stages with testable SQL and deterministic outputs (manifested, versioned, idempotent).
- **Product** — Ship a global, responsive map with predictable performance, a clear legend, and honest coverage messaging.

### 1.2 Non‑Goals (v1)

- Statistical smoothing (Empirical‑Bayes) — planned for v2.
- Flight‑aware segmentation using the OpenSky flights archive — planned for v2 (v1.1 uses gap‑based segmentation).
- Real‑time ingestion/streaming — v1 is batch (monthly).

### 1.3 Decision Log (frozen for v1)

- **Denominator**: *Unique flight segments touching a cell per period* (deduped)
- **Dual metrics**: Track both `incidents_unique` (for rates) and `incidents_coverage` (for visualization)
- **Min visibility thresholds** (resolution-scaled):
  - r3: ≥25 flights/week
  - r4: ≥50 flights/week
  - r5: ≥100 flights/week
- **Incident quality gates** (temporal-based):
  - Minimum 5 consecutive samples over 60 seconds
  - Squawk persistence >45 seconds
  - Airborne validation (≤30% ground samples)
  - Roller-dial suppression (77XX→7700 patterns)
  - Confidence score: 0-100 composite
- **Incident debounce**: 15 minutes (type-specific within segment)
- **Storage**: Hybrid GeoParquet with geometry + coordinate arrays
- **Development progression**: 1-hour sample → 1-day validation → 7-day production
- **Testing strategy**: Synthetic boundaries + real samples + statistical validation
- **Coverage metric**: Points-per-flight median as sole indicator
- **Interpolation**: Conservative 5km/30s due to missing velocity data
- **Error handling**: Fail fast on logic errors, 3 retries with backoff for network errors
- **Tiles**: PMTiles via Tippecanoe, resolution-specific packages
- **Zoom→H3 mapping**: z4–5→r3; z6–7→r4; z8–9→r5; z10–11→r6; z12+→r7

### 1.4 ADS-B Data Characteristics

**Available Fields**: `time`, `icao24`, `callsign`, `lat`, `lon`, `squawk`, `onground`, `alert`

**Normal Data Patterns**:
- ~35% of records have no squawk code (standard for ADS-B)
- Receiver information not available in this dataset
- Velocity and altitude data not included
- These are characteristics of ADS-B networks, not data quality issues

**Mitigation Strategy**:
- **Missing receiver diversity** → Strengthen temporal validation (5+ samples)
- **No velocity/heading** → Conservative 5km/30s interpolation
- **Partial squawk coverage** → Track observable ratios, detect only confirmed
- **No altitude data** → Focus on lateral movement patterns

---

## 2. Functional Requirements

### 2.1 Core Flows

1) **Ingest & cache** OpenSky states history into monthly Parquet partitions.
2) **Transform** into flight segments (v1.1 gap‑based), detect & debounce incidents.
3) **Aggregate to H3** per month/resolution with counts, rates, and summary attributes.
4) **Package as PMTiles** (MVT) per resolution with **multi‑month** attribute.
5) **Render map** with a hybrid color scale; expose filters and drill‑downs.

### 2.2 Filters & Controls

- Month picker (single month at a time; time slider optional if needed).
- Squawk selector: **All / 7500 / 7600 / 7700**.
- Resolution lock (toggle advanced) to hold the H3 res across zoom.
- AOI search (fly‑to), optional.
- Reset filters.

### 2.3 Outputs

- Interactive map (WebGL) with informative legend & tooltips.
- Drill‑down table per **(month, h3_index, resolution, filter)**.
- Download CSV for the drill‑down table (guarded by size).

---

## 3. Data Sources & Schemas

### 3.1 OpenSky States History (via Trino)

- **Table**: `minio.osky.state_vectors_data4`
- **Required fields**: `time` (unix s), `icao24`, `callsign` (nullable), `lat`, `lon`, `baroaltitude` (nullable), `geoaltitude` (nullable), `velocity` (nullable), `heading` (nullable), `vertrate` (nullable), `squawk` (nullable), `onground` (boolean), `alert` (boolean).
- **Partition**: Table is partitioned by `hour` (unix timestamp of hour start, not `day`).
- **Query window**: calendar months (UTC), extracted daily.
- **Access**: Direct Trino connection with password authentication; streaming via DuckDB for memory efficiency.
- **Implementation**: Uses `trino` Python client with JWT authentication from password grant flow.

### 3.2 OpenSky Aircraft Registry

- **Format**: CSV snapshot or table; left‑join on `icao24` (string/hex).
- **Fields used**: `typecode` (ICAO Doc 8643), `model`, `manufacturer`, `registration`, `owner` (if present; not displayed).
- **Notes**: coverage is incomplete; expect nulls and stale rows.

### 3.3 Derived Concepts

- **Squawk type**: map `7500`→unlawful interference, `7600`→lost comms, `7700`→general emergency.
- **Great‑circle distance**: WGS‑84 haversine for interpolation & segment length checks.

---

## 4. ETL Pipeline (Batch)

> All stages are **idempotent**. Each write includes a **MANIFEST.toml** with `{data_version, code_version, source_range, row_counts, checksum}`. Storage uses local filesystem for v1.

### 4.1 Stage‑1 Extraction (Raw Cache)

**Purpose**: Pull states into **monthly** Parquet partitions on local filesystem.
**Inputs**: `year, month` (UTC).
**Columns**: only required fields (§3.1) to reduce size.
**Chunking**: Query by **hour** (24 queries per day), stream via DuckDB to Parquet.
**Output paths**:
- Hourly: `data/raw/states_YYYY-MM-DD_HH.parquet` (intermediate)
- Daily: `data/raw/states_YYYY-MM-DD.parquet` (consolidated)

**Implementation Details**
- Query each hour partition individually: `WHERE hour = unix_timestamp`
- Collect results in memory then use PyArrow zero-copy to DuckDB
- Atomic writes with .tmp files for crash safety
- Resume support: skip existing hourly/daily files
- Rate limiting retry with exponential backoff

**Guards**
- Reject rows with `lat/lon` null.
- Drop obviously invalid positions (|lat|>90, |lon|>180).
- Enforce monotonic `time` type.
- **Fail fast** on Trino error or schema change; no retries in v1.

### 4.2 Stage‑2 Transformation (Segments & Incidents)

**4.2.1 Segment Builder**
- Partition by `icao24`; order by `time`.
- Start new segment when **gap ≥ 20 minutes** between consecutive points.
- Filter segments with **duration <10 min AND distance <30 km** (OR condition for keeping).
- **Note**: Interpolation deferred to v1.1 due to complexity with pure SQL approach
- Assign `segment_id = icao24 || '_' || segment_number` for uniqueness.
- Track `squawk_coverage_ratio` = observable squawk samples / total samples

**Segment Storage Schema (Actual Implementation):**
```sql
-- Output from segment_pipeline.sql
segment_id VARCHAR,           -- e.g., "abc123_1"
icao24 VARCHAR,              -- Aircraft identifier
start_time INTEGER,          -- Unix timestamp
end_time INTEGER,            -- Unix timestamp
duration_seconds INTEGER,    -- end_time - start_time
distance_km DOUBLE,          -- Haversine distance sum
point_count INTEGER,         -- Number of raw points
squawk_count INTEGER,        -- Points with non-NULL squawk
squawk_coverage_ratio DOUBLE, -- squawk_count / point_count
keep_reason VARCHAR,         -- 'duration' | 'distance' | 'both'
points STRUCT[],            -- Array of point structs with all fields
```

**Implementation Notes**:
- Uses DuckDB STRUCT arrays instead of separate geometry columns
- Single SQL pipeline (segment_pipeline.sql) handles all transformations
- No intermediate Python DataFrames - direct COPY TO Parquet
- Memory-safe execution with configurable limits

**4.2.2 Temporal Quality Gates & Confidence Scoring**
Validate emergency squawks through temporal patterns:
- **Temporal stability**: Minimum 5 consecutive samples within 60 seconds
- **Signal persistence**: Squawk must persist >45 seconds
- **Airborne validation**: ≤30% of samples show `onground=true`
- **Roller-dial suppression**: Filter transitions like 77XX→7700

**Confidence Score Calculation (0-100)**:
- Temporal stability: 40% weight (samples_in_window / 5, capped at 1.0)
- Signal persistence: 30% weight (duration / 60s, capped at 1.0)
- Airborne ratio: 20% weight (1 - ground_ratio)
- Squawk coverage: 10% weight (observable_samples / total_samples)

Categories: High (>70), Medium (40-70), Low (<40)

**4.2.3 Incident Detection & Debounce**
Process only records with observable squawk codes (~65% of data):
- Skip records with NULL/empty squawk (normal for ADS-B)
- Incident starts when validated squawk enters {7500, 7600, 7700}
- **Debounce**: Same-type events <15 minutes apart are merged
- Minimum 30% squawk coverage for segment to be incident-eligible

Record fields:
  - Core: `incident_id`, `segment_id`, `squawk_type`, `start_time`, `end_time`
  - Quality: `confidence_score`, `samples_count`, `squawk_coverage_ratio`
  - Validation: `passes_quality_gates`, `confidence_category`
  - Enrichment: `callsign`, `registration`, `typecode` (nullable)

**4.2.4 Segment→H3 Coverage**
- Compute H3 cells touched by segment polyline for resolutions r3–r7
- Each resolution is computed independently from raw segment data (not hierarchically)
- Use coordinate arrays with h3-duckdb extension functions
- Track both unique segments and coverage per cell
- NULL coordinate points are filtered but don't invalidate the segment

**2.2.4 Aircraft Enrichment (left‑join)**
- Join aircraft CSV on `icao24` to add `typecode`, `model`, `manufacturer`, `registration`.
- Keep original keys for lineage; allow nulls.

**Outputs**
- `data/curated/segments/year=YYYY/month=MM/segments.parquet`
- `data/curated/incidents/year=YYYY/month=MM/incidents.parquet`

### 4.3 Stage‑3 Aggregation (Per Period & Resolution)

For each period (week for prototype) and H3 **resolution r ∈ {3..7}**:

**Dual Metrics Approach:**
- `flights_unique` = Count of unique segments touching cell (denominator)
- `incidents_unique` = Count of unique incidents in cell (for rates)
- `incidents_coverage` = Total incident-cell intersections (for heatmap) - if one incident crosses 5 cells, each cell gets incidents_coverage=1
- `rate_unique_ppm` = `incidents_unique / flights_unique * 1e6`
- `rate_coverage_ppm` = `incidents_coverage / flights_unique * 1e6`

**Coverage Quality Metrics:**
- `points_per_flight` = Total points / unique segments within each cell (calculated per cell)
- `points_per_flight_median` = Primary coverage indicator (median PPF within each cell)
- Coverage categories based on observation density per cell:
  - Excellent: ≥10 points per flight
  - Good: 6-9 points per flight
  - Limited: 3-5 points per flight
  - Poor: <3 points per flight (consider masking)

**Statistical Confidence:**
- `confidence_category` based on flight counts:
  - High: >500 flights (opacity 100%)
  - Medium: 100-500 flights (opacity 60%)
  - Low: <100 flights (opacity 30%)
- Future v1.1: Add Empirical-Bayes smoothed rates with credible intervals

**Visibility Thresholds (resolution-scaled):**
- r3: Mask if <25 flights/week
- r4: Mask if <50 flights/week
- r5: Mask if <100 flights/week
- r6-r7: Scale proportionally by cell area

**Output**
- `/aggregates/res=r{r}/aggregates_YYYYMM.parquet` (+ MANIFEST.toml)
- `/aggregates/res=r{r}/incident_h3_mapping_r{r}.parquet` (incident_id ↔ h3_cell lookup for API)

### 4.4 Stage‑4 Tile Build (PMTiles/MVT)

**Pipeline**: DuckDB exports H3 hexagons to compressed GeoJSONL → Tippecanoe generates PMTiles.
**Packaging**: One **PMTiles** per **resolution** containing **multiple months**; each feature carries `month` as an attribute.

**Layer name**: `hotspots_r{r}`.
**Feature**: one polygon per H3 cell.
**Attributes** (minimal + summaries):
```
month (YYYY-MM)
h3_res (int)
h3_index (string)      # base16
flights (int)
incidents_all (int)
incidents_7500 (int)
incidents_7600 (int)
incidents_7700 (int)
rate_all_ppm (float)
top_aircraft_typecode (string|null)
coverage_note (enum: good|partial|mask)
```
**Tile quality**
- Geometry simplification per zoom to keep tile size reasonable (target: **<200 KB** typical tile).
- Quantize coordinates; 1–2 decimal digits in attributes where appropriate.
- Validate attribute presence and types.

**Output**
- `/tiles/h3_r{r}/hotspots.pmtiles` (with accompanying TileJSON).

---

## 4.5 SQL Development Methodology

### Core Philosophy

**SQL as the Computation Engine**: DuckDB handles all heavy data transformations through pure SQL. Python serves only as orchestration - configuration loading, parameter passing, and file management. This separation ensures memory-safe processing of billion-row datasets.

### Critical SQL Patterns

**1. Memory Configuration First**
```sql
-- ALWAYS start SQL files with memory settings
SET memory_limit = '{{ memory_limit }}';
SET threads = {{ threads }};
SET temp_directory = '{{ temp_directory }}';
```

**2. Stream Through CTEs**
```sql
COPY (
    WITH raw_data AS (...),
         transformed AS (...),
         filtered AS (...)
    SELECT * FROM filtered
) TO '{{ output_path }}' (FORMAT PARQUET, COMPRESSION 'zstd')
```

**3. Avoid Memory Bombs**
```sql
-- BAD: ORDER BY in aggregation
ARRAY_AGG({...} ORDER BY time)

-- GOOD: Pre-order, then aggregate
WITH ordered AS (SELECT * FROM ... ORDER BY icao24, time)
SELECT ARRAY_AGG({...}) FROM ordered
```

**4. List Operations Over UNNEST**
```sql
-- Memory-safe array filtering
list_count(list_filter(points, p -> p.squawk = '7700'))
```

### File Organization

```
aviation_anomaly/sql/
├── segment_pipeline.sql       # Gap-based flight segmentation
├── incident_detection.sql     # Emergency detection with quality gates
└── h3_aggregation.sql         # Future: Spatial aggregation
```

### Template Variables via qck

```python
params = {
    "input_path": str(input_file),
    "output_path": str(temp_path),
    "gap_threshold": config.segments.gap_minutes * 60,
    "memory_limit": config.duckdb.memory_limit,
    "threads": config.duckdb.threads,
    "temp_directory": config.duckdb.temp_directory,
}
```

### Python Integration Pattern

```python
from pathlib import Path
from uuid import uuid4
from qck import qck

def process_with_sql(date: datetime.date, config: Config) -> Path:
    """Standard pattern for SQL pipeline execution."""
    # Generate unique session ID for temp files (prevents collisions)
    session_id = uuid4().hex[:8]
    temp_path = output_dir / f".segments_{session_id}.parquet"
    final_path = output_dir / f"segments_{date}.parquet"

    params = {
        "input_path": str(input_file),
        "output_path": str(temp_path),
        "memory_limit": config.duckdb.memory_limit,
        "threads": config.duckdb.threads,
    }

    # Execute SQL pipeline - writes directly to temp_path
    sql_file = Path(__file__).parent / "sql" / "segment_pipeline.sql"
    qck(str(sql_file), params=params)

    # Atomic rename for crash safety
    temp_path.rename(final_path)
    return final_path
```

**Why Session IDs?** Prevents file collisions during concurrent runs or crashes. The `.` prefix hides temp files from directory listings.

### Testing SQL Pipelines

**Test Production SQL, Not Reimplementations**

```python
# tests/conftest.py - Shared test fixtures
@pytest.fixture
def emergency_segment():
    """Builder for test segments with emergencies."""
    def _builder(*, icao24="test", emergency_samples=10, emergency_span_s=60):
        points = []
        for i in range(emergency_samples):
            points.append({
                "time": int(1000 + i * emergency_span_s / (emergency_samples - 1)),
                "squawk": "7700",
                "onground": False
            })
        return {
            "segment_id": f"{icao24}_1",
            "icao24": icao24,
            "points": points,
            # ... other fields
        }
    return _builder

@pytest.fixture
def run_incident_detection():
    """Run actual SQL pipeline with test data."""
    def _runner(segments_data: list[dict]) -> list[dict]:
        # Write test segments to parquet
        # Execute production SQL via qck
        # Return incidents as dicts
        ...
    return _runner
```

```python
# tests/test_incident_detection.py
def test_temporal_quality_gate(emergency_segment, run_incident_detection):
    # Arrange: Create test data with clear intent
    segment = emergency_segment(emergency_samples=5, emergency_span_s=60)

    # Act: Run ACTUAL production SQL
    incidents = run_incident_detection([segment])

    # Assert: Verify behavior
    assert len(incidents) == 1  # Detected
```

**Test Fixture Organization**:
- `tests/conftest.py`: All shared fixtures (data builders, pipeline runners)
- Test files import fixtures automatically via pytest
- Each fixture returns a builder function for flexibility

### Key Lessons Learned

**Critical DO's:**
- ✓ SET memory limits first in every SQL file
- ✓ Use session IDs for temp files: `.segments_{uuid}.parquet`
- ✓ Test fixtures in `conftest.py` that call production SQL
- ✓ Stream through CTEs, never materialize DataFrames
- ✓ Atomic renames for crash safety

**Critical DON'Ts:**
- ✗ Never use `ORDER BY` in `ARRAY_AGG`
- ✗ Never use `pd.read_sql()` or `.df()` on production data
- ✗ Never reimplement SQL logic in tests
- ✗ Never forget 1-based array indexing in DuckDB
- ✗ Never create temporary tables (use CTEs)

---

## 5. Frontend Application

### 5.1 Technology

- Map rendering via **MapLibre GL** with vanilla JavaScript (no build step required).
- PMTiles source using a PMTiles protocol handler (HTTP range requests).
- **HTMX** for non‑map UI controls (filters, drill-down interactions).
- No heavy build chain required; serve static HTML/JS/CSS files.

### 5.2 UX Requirements

**5.2.1 Coverage Communication**
- **Persistent header**: "Emergency squawk rates from observed traffic. Coverage and procedures vary by region."
- **Legend enhancement**:
  - Color scale with confidence indicators (opacity shows data reliability)
  - Coverage quality overlay (dots/hatching for limited coverage areas)
  - "About the Data" expandable section explaining limitations
- **Regional context**: Tooltips include note about regional procedural differences

**5.2.2 Map Visualization**
- **Dual-layer approach**:
  - Primary: Incident rate heatmap with confidence-based opacity
  - Overlay: Coverage quality indicators (optional toggle)
- **Tooltip content**:
  - Rates: Both unique and coverage metrics
  - Confidence: Flight count and category
  - Coverage: Quality score and category
  - Context: Regional notes when relevant
- **Color scheme**: Color-blind safe with distinct patterns for low confidence

**5.2.3 Filters & Controls**
- **Time selector**: Day view or full week
- **Squawk filter**: All / 7500 / 7600 / 7700
- **Coverage overlay**: Toggle on/off
- **Confidence display**: Raw vs smoothed rates (v1.1)
- **Resolution lock**: Advanced option to fix H3 resolution

**5.2.4 Drill-down Details**
- **Enhanced incident table**:
  - Core: Time, squawk, aircraft ID, callsign
  - Quality: Confidence score, sample count
  - Context: Phase of flight (when available in v2)
- **Export options**: CSV with full metadata
- **Pagination**: 200 rows max, clear navigation

### 5.3 Performance Budgets

- Initial map render: **<2.0 s** on a 4G connection (Fast 3G Lighthouse profile acceptable to 3.0 s).
- Interaction latency (filter change): **<300 ms** to visual update (cached tiles).
- PMTiles size budgets (indicative): r3 **≤60 MB**, r4 **≤120 MB**, r5 **≤250 MB** per multi‑month package.

### 5.4 Zoom→H3 Mapping (fixed)

- z4–5 → r3 (~40 km edge)
- z6–7 → r4 (~15 km)
- z8–9 → r5 (~6 km)
- z10–11 → r6 (~2.5 km)
- z12+ → r7 (~1 km)

---

## 6. APIs & File Endpoints

### 6.1 Tile Serving

- GET `/tiles/h3_r{r}/hotspots.pmtiles` — static file on CDN.
- GET `/tiles/h3_r{r}/tile.json` — TileJSON with attribution, bounds, min/max zoom, layer name, and a list of available `month` values (metadata).

### 6.2 Drill‑Down Data (per cell, per month)

- **Implementation**: Click CLI with embedded FastAPI server.
- **Data Architecture**: Pre-computed `incident_h3_mapping_r{r}.parquet` tables enable fast lookups (incident_id ↔ h3_cell).
- GET `/api/drilldown?month=YYYY-MM&h3_res=r&h3_index=hex&sq=all|7500|7600|7700&limit=200&offset=0`
**Response**:
```json
{
  "meta": {"month":"2025-05","h3_res":4,"h3_index":"8928308280fffff","count": 132},
  "rows": [
    {
      "timestamp_start":"2025-05-14T12:45:02Z",
      "timestamp_end":"2025-05-14T12:55:30Z",
      "squawk_type":"7700",
      "icao24":"a1b2c3",
      "callsign":"SAS123 ",
      "registration":"SE-ABC",
      "typecode":"A20N"
    }
  ]
}
```
- Backed by `data/curated/incidents` parquet; server enforces row caps and projects only needed columns.

---

## 7. Testing & Validation

### 7.1 Testing Strategy

**7.1.1 Development Dataset Hierarchy**
- **Sample**: 1 hour (July 1, 00:00-01:00 UTC) - 30M records for rapid iteration
- **Validation**: 1 day (July 1) - 730M records for integration testing
- **Production**: 7 days (July 1-7) - 5.1B records for final validation

**Performance Expectations (with dense interpolation):**
- 1-hour processing: <30 seconds
- 1-day processing: <15 minutes
- 7-day processing: <2 hours

**7.1.2 Three-Layer Testing Approach**

**Synthetic Boundary Tests:**
- Gap detection at exactly 20 minutes (fail at 19:59, pass at 20:00)
- Segment filtering at 10min/30km thresholds
- Dense interpolation at 5km/30s intervals
- Temporal quality gates: 4 vs 5 samples in 60s window
- Signal persistence: 44s vs 45s threshold
- Ground ratio: 29% vs 30% threshold
- Confidence score calculation accuracy
- Roller-dial patterns (7703→7700)

**Real Data Golden Tests:**
- Extract 10 representative aircraft from hour 00
- Manually verify segment boundaries and incidents
- Store as regression test fixtures
- Validate quality gate decisions

**Statistical Validation:**
- Expected segments/day: 10K-20K range
- Duration distribution: log-normal with median 1-2 hours
- H3 coverage per segment: 50-200 cells at r5
- Incident rate: 1-10 per 1000 flights (varies by region)

### 7.2 Integration Tests

- **Test Data**: Real OpenSky samples (48h) for integration tests; synthetic data for edge cases.
- **Mini month** (48h real sample + synthetic edge cases): run **Stage‑1→4**; compare MANIFEST counts to expectations.
- **Tile validation**: Tippecanoe validates MVT encoding during generation; size budgets checked programmatically. No separate validation tools needed (YAGNI principle).

### 7.3 Frontend Tests

- Smoke test loads PMTiles and renders r4 at z6–7; filter toggles update style without network errors.
- Tooltip & drill‑down snapshot tests; CSV export validates headers and row counts.

### 7.4 Acceptance Criteria

- Map loads globally at r4 with the hybrid legend; switching squawk filter updates counts and colors.
- Drill‑down returns expected rows for known test cells; IDs and timestamps make sense.
- Cells with `<50` flights are greyed and excluded from stats.
- PMTiles metadata lists all months packaged; selecting each month filters the layer.

---

## 8. Operational Considerations

### 8.1 Versioning & Lineage

- Every dataset/tile bundle includes a **MANIFEST.toml** with:
  `{source_snapshot (start_ts,end_ts), code_version, data_version, created_at, row_counts, checksum (SHA256), config_hash}`.
- Manifests written atomically (write to temp file, then rename).
- Folder names are immutable; new runs write to a new `data_version` folder and update a lightweight pointer file `LATEST`.

### 8.2 Configurability (TOML config file)

**Format**: TOML configuration file (`config.toml`) loaded via Python's `tomllib`.
**CLI**: Click accepts `--config` parameter with default path (required).

```toml
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

[duckdb]
memory_limit = "4GB"
threads = 4
temp_directory = "/tmp/duckdb"
max_temp_directory_size = "100GB"
```
- All thresholds are surfaced centrally; changing them increments `data_version`.
- DuckDB configuration enables memory-safe processing of billion-row datasets.

### 8.3 Logging & Error Handling

**Structured Logging:**
- Required fields: `stage`, `dataset`, `partition`, `duration_ms`, `row_counts`
- Quality metrics: `quality_gates_passed`, `quality_gates_failed`
- Coverage metrics: `coverage_score`, `receiver_diversity`

**Error Handling Strategy:**
- **Logic errors**: Fail fast (schema mismatch, SQL errors, invalid data)
- **Transient errors**: 3 retries with exponential backoff
  - Network timeouts
  - Rate limiting (respect retry-after headers)
  - Connection drops
- **Logging**: Every retry attempt logged with failure category

**Retry Implementation Pattern:**
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    retry=retry_if_exception_type(TransientError),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
```

### 8.4 Security & Privacy

- Drill‑down exposes **callsign and registration**; document this in UI and T&Cs.
- Respect OpenSky terms; do not redistribute raw data beyond what is permitted.
- No PII beyond aircraft identifiers; no user data collected.

---

## 9. Risks & Mitigations

- **Coverage bias**: prominently flagged by `coverage_note`; legend clarifies.
- **Sparse denominators**: mask `<50` flights; hybrid color scale to avoid misleading extremes.
- **Tile bloat**: strict attribute set; geometry simplification and quantization; PMTiles packaging.
- **Operational fragility** (v1): fail‑fast increases rebuilds; v2 can add retries/backoff.
- **Type join gaps**: show nulls; do not rely on type for filtering logic in v1.

---

## 10. Future Work

### 10.1 Lessons from 7-Day Prototype

**To be documented during implementation:**
- Validated assumptions about data volume and processing
- Performance benchmarks for each stage
- Quality gate effectiveness metrics
- Coverage patterns and regional variations
- Technical debt and optimization opportunities

### 10.2 v2.0 Features (Priority Order)

**Flight-aware Segmentation:**
- Use `flights_data4` table for official flight segments
- Phase-of-flight attribution (taxi, takeoff, cruise, approach, landing)
- Airport proximity analysis (<50km from major airports)
- More accurate incident-to-flight attribution

**Empirical-Bayes Smoothing:**
- Beta-binomial model for rate estimation
- Credible intervals in all visualizations
- Handles sparse data appropriately
- User toggle between raw and smoothed rates

**Cause Inference (from OpenSky report patterns):**
- Duration analysis: Medical emergencies (longer) vs technical issues (shorter)
- Aircraft type correlations with incident types
- Time-of-day and day-of-week patterns
- Weather correlation when data available

### 10.3 v2.1 Enhancements

**Regional Profiling:**
- Country-level 7700 usage rate baselines
- ATC zone boundary overlays
- Procedural difference documentation
- Normalization by regional practices

**Advanced Analytics:**
- Multi-period comparisons and trends
- Anomaly detection for unusual spikes
- Seasonal pattern analysis
- Fleet-specific incident rates

---

## Appendix A — Example SQL/Pseudocode

> Actual DuckDB dialect as implemented.

**Segment gaps (from segment_pipeline.sql)**
```sql
-- Calculate time gaps and assign segment IDs
WITH gaps_detected AS (
    SELECT *,
           time - LAG(time) OVER (PARTITION BY icao24 ORDER BY time) AS time_gap,
           CASE
               WHEN time - LAG(time) OVER (PARTITION BY icao24 ORDER BY time) >= 1200
                    OR LAG(time) OVER (PARTITION BY icao24 ORDER BY time) IS NULL
               THEN 1 ELSE 0
           END AS new_segment_flag
    FROM raw_data
),
with_segment_ids AS (
    SELECT *,
           SUM(new_segment_flag) OVER (PARTITION BY icao24 ORDER BY time) AS segment_num,
           icao24 || '_' || CAST(SUM(new_segment_flag)
                            OVER (PARTITION BY icao24 ORDER BY time) AS VARCHAR) AS segment_id
    FROM gaps_detected
)
-- Important: ARRAY_AGG without ORDER BY to avoid memory issues
SELECT segment_id, icao24, MIN(time) AS start_time, MAX(time) AS end_time,
       ARRAY_AGG({'time': time, 'lat': lat, 'lon': lon, ...}) AS points
FROM with_segment_ids
GROUP BY segment_id, icao24;
```

**Incident debounce (per segment & type)**
```sql
-- Assume rows only when squawk in {7500,7600,7700}, per segment & type
WITH e AS (
  SELECT *, time - LAG(time) OVER (PARTITION BY segment_id, squawk_type ORDER BY time) AS dt
  FROM segment_events
),
burst AS (
  SELECT *, CASE WHEN dt IS NULL OR dt > 15*60 THEN 1 ELSE 0 END AS new_burst
  FROM e
)
SELECT segment_id, squawk_type,
       MIN(time) AS t_start, MAX(time) AS t_end,
       COUNT(*) AS frames
FROM (
  SELECT *, SUM(new_burst) OVER (PARTITION BY segment_id, squawk_type ORDER BY time) AS burst_id
  FROM burst
) b
GROUP BY segment_id, squawk_type, burst_id;
```

**Aggregation per H3 cell**
```sql
-- flights: unique segments that touch cell; incidents: count bursts touching cell
SELECT month, h3_res, h3_index,
       COUNT(DISTINCT segment_id) AS flights,
       SUM(incidents_all) AS incidents_all,
       SUM(incidents_7500) AS incidents_7500,
       SUM(incidents_7600) AS incidents_7600,
       SUM(incidents_7700) AS incidents_7700,
       (CASE WHEN COUNT(DISTINCT segment_id) > 0
             THEN 1e6 * SUM(incidents_all)::DOUBLE / COUNT(DISTINCT segment_id)
             ELSE NULL END) AS rate_all_ppm
FROM cell_facts
GROUP BY month, h3_res, h3_index;
```

---

## Appendix B — Acceptance Checklist (Dev sign‑off)

- [ ] Stage‑1 writes monthly raw Parquet with manifest; row counts stable.
- [ ] Stage‑2 segments match gap/duration/distance rules; line‑cover prevents cell skips.
- [ ] Incidents are debounced at **15 min** within segments & type.
- [ ] Aggregates honor mask rule `<50` flights; coverage note set per thresholds.
- [ ] PMTiles per resolution pass size and attribute validations.
- [ ] Frontend renders r4 globally; tooltips & filters match attributes.
- [ ] Drill‑down API returns correct rows and enforces limits.
- [ ] Documentation: legend copy, data disclaimer, API schemas published.
