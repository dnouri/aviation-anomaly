# Aviation Anomaly Tracker — Detailed Specification

> Status: **Draft for Dev Handoff**
> Scope: **Global but shallow** (one multi-month package; Phase‑1 map validated at H3 r4, with r3–r7 prepared)
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

- **Denominator**: *Unique flight segments touching a cell per month* (deduped)
- **Min visibility**: mask cells with **<50 flights/month**
- **Incident categories**: show **aggregate** and offer **per‑type filters** (7500/7600/7700)
- **Incident debounce** (type-specific within same segment): **15 minutes**
- **Include aircraft type** (via OpenSky aircraft DB; nulls allowed)
- **Tiles**: **PMTiles** packaging for MVT, multi‑month per resolution
- **Zoom→H3**: z4–5→r3; z6–7→r4; z8–9→r5; z10–11→r6; z12+→r7
- **Error handling**: **fail fast** on pipeline errors (no retries in v1)
- **Phase‑1 map**: **global**, one multi‑month PMTiles, **r4** baseline; r3–r7 generated for future zooms
- **Coverage note**: **Mixed rule** (points/flight & flights thresholds)
- **Identifiers in drill‑down**: **callsign + registration** when available

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

**2.2.1 Segment Builder (v1.1)**
- Partition by `icao24`; order by `time`.
- Start a segment at first point or when **gap > 20 min**.
- End segment at the last point before the gap.
- Discard segments with **duration <10 min AND distance <30 km**.
- Compute **polyline** via great‑circle **interpolation** at max **10 km** chord or **60 s** time step (whichever finer) to avoid cell skips.
- Assign `segment_id = hash(icao24, start_time, end_time)`.

**2.2.2 Segment→H3 cells (line cover)**
- For each segment polyline, compute H3 line‑cover for **r3–r7** using h3-duckdb extension.
- **Dedup rule**: a segment contributes **at most 1** to the **denominator** per `(cell, month)`.

**2.2.3 Incident Detection & Debounce**
- On a segment, an **incident** starts when squawk enters {7500, 7600, 7700}; ends when it leaves.
- **Debounce**: events of the **same type** separated by **<15 min** are merged.
- Record: `incident_id`, `segment_id`, `icao24`, `type`, `t_start`, `t_end`, `duration_s` (cap at 90 min for stats), `callsign_first`, `registration` (from join), `typecode` (nullable).
- For H3 aggregation, an incident contributes **1** to each **cell** intersected by the **segment** (not duration‑weighted in v1).

**2.2.4 Aircraft Enrichment (left‑join)**
- Join aircraft CSV on `icao24` to add `typecode`, `model`, `manufacturer`, `registration`.
- Keep original keys for lineage; allow nulls.

**Outputs**
- `data/curated/segments/year=YYYY/month=MM/segments.parquet`
- `data/curated/incidents/year=YYYY/month=MM/incidents.parquet`

### 4.3 Stage‑3 Aggregation (Per Month & Resolution)

For each month and each H3 **resolution r ∈ {3..7}**:

- `flights` = **number of unique `segment_id`** that touched the cell (deduped).
- `incidents_*` = counts of incidents touching the cell (aggregate and per type).
- `rate_all_ppm` = `incidents_all / flights * 1_000_000` (if `flights`>0, else null).
- `points_per_flight_median` = median **raw** points per (`segment_id`, cell) for coverage.
- `top_aircraft_typecode` = mode of incident‑carrying segments’ `typecode` (ties broken by frequency then lexicographically).
- `coverage_note` = **Good** if `points_per_flight_median≥4 && flights≥100`; **Partial** otherwise; **Mask** if `flights<50`.

**Output**
- `/aggregates/res=r{r}/aggregates_YYYYMM.parquet` (+ MANIFEST.toml)

### 4.4 Stage‑4 Tile Build (PMTiles/MVT)

**Pipeline**: DuckDB exports H3 hexagons to GeoJSON → Tippecanoe generates PMTiles.
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

## 5. Frontend Application

### 5.1 Technology

- Map rendering via **MapLibre GL** with vanilla JavaScript (no build step required).
- PMTiles source using a PMTiles protocol handler (HTTP range requests).
- **HTMX** for non‑map UI controls (filters, drill-down interactions).
- No heavy build chain required; serve static HTML/JS/CSS files.

### 5.2 UX Requirements

- **Legend**: hybrid color scale (fixed base + quantile tail); grey = “Insufficient data (<50 flights)”.
- **Tooltip (on hover/click)**:
  - `rate_all_ppm`, `flights`, `incidents_all`, breakdown (7500/7600/7700), `top_aircraft_typecode` (if any), `coverage_note`.
- **Filters**: month (single), squawk type (All / 7500 / 7600 / 7700).
- **Resolution control** (advanced): lock to a chosen H3 res.
- **Drill‑down (side panel)**: table for the selected (month, cell):
  - `timestamp_start`, `timestamp_end`, `squawk_type`, `icao24`, `callsign`, `registration`, `typecode` (nullable).
  - Sort by time desc; CSV export; max 200 rows (paginate).
- **Accessibility**: color‑blind‑safe palette; keyboard focus indicators; descriptive ARIA labels.

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

### 7.1 Unit Tests

- **SQL Testing**: Pure SQL tests using separate .sql files with test harness.
- **Segment builder**: gap boundaries (19m = same, 20m = new), min duration/distance filters.
- **Interpolation**: ensures intermediate points prevent H3 skips on long legs.
- **Line cover**: property‐based tests on synthetic polylines vs known cell sets.
- **Debounce**: 5/10/15/60‑min scenarios; type‑specific merging only.
- **Aggregation math**: denominator dedupe; rate calculation; coverage note thresholds.

### 7.2 Integration Tests

- **Test Data**: Real OpenSky samples (48h) for integration tests; synthetic data for edge cases.
- **Mini month** (48h real sample + synthetic edge cases): run **Stage‑1→4**; compare MANIFEST counts to expectations.
- **Tile validation**: parse PMTiles, check attribute presence/types, tile count heuristics, and size budgets.

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
**CLI**: Click accepts `--config` parameter with default path.

```toml
[segments]
segment_gap_minutes = 20
segment_min_duration_min = 10
segment_min_distance_km = 30

[incidents]
debounce_minutes = 15

[aggregation]
h3_resolutions = [3, 4, 5, 6, 7]
min_flights_visible = 50
coverage_good_pts_per_flt = 4
coverage_good_min_flights = 100

[interpolation]
interp_max_chord_km = 10
interp_max_step_s = 60
```
- All thresholds are surfaced centrally; changing them increments `data_version`.

### 8.3 Logging

- Structured logs with `stage`, `dataset`, `partition`, `duration_ms`, `row_counts`.
- **Fail fast**: pipeline aborts on errors (schema mismatch, extraction failure, write errors).
- Metrics exported as counters/gauges if infra allows; otherwise JSON logs suffice.

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

## 10. Future Work (v2 Roadmap)

- **Empirical‑Bayes** smoothing with beta‑binomial; show credible intervals in tooltips.
- **Flight‑aware segmentation** via OpenSky flights archive; phase‑of‑flight inference; airport proximity context.
- **Retries & backoff**, alerting; incremental rebuilds.
- **Region‑specific registries** (FAA, CAA) to enrich aircraft type coverage.
- **Time animation** and deltas vs prior month; per‑type small multiples.

---

## Appendix A — Example SQL/Pseudocode

> The exact SQL dialect may vary; shown here for DuckDB + H3.

**Segment gaps**
```sql
-- Per icao24, ordered by time
WITH s AS (
  SELECT *,
         time - LAG(time) OVER (PARTITION BY icao24 ORDER BY time) AS dt
  FROM states
),
flags AS (
  SELECT *, CASE WHEN dt IS NULL OR dt > 20*60 THEN 1 ELSE 0 END AS new_seg
  FROM s
),
segmented AS (
  SELECT *, SUM(new_seg) OVER (PARTITION BY icao24 ORDER BY time) AS seg_no
  FROM flags
)
SELECT icao24, MIN(time) AS t_start, MAX(time) AS t_end,
       array_agg([lat,lon] ORDER BY time) AS path
FROM segmented
GROUP BY icao24, seg_no;
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
