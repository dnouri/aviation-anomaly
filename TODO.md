# Aviation Anomaly Tracker — Implementation TODO

> **Methodology**: Test-Driven Development (TDD) with strict red-green-refactor cycles
> **Approach**: Incremental delivery of working software, phase by phase
> **Quality**: Commit only after tests pass, linting succeeds, and types check

## Core Principles

1. **Red → Green → Refactor**: Every task follows this cycle without exception
2. **Working Software**: Each phase delivers runnable, tested code
3. **Small Steps**: Tasks are 1-2 hours; phases are 1-2 days maximum
4. **Test First**: Write the failing test before any implementation
5. **Commit Discipline**: Only commit complete, working phases

## Technical Constraints

- **uv**: Package management via uv and `pyproject.toml`
- **Makefile**: Common commands via `Makefile`, see `make help`
- **Database**: DuckDB with h3-duckdb extension (no Pandas)
- **SQL**: Separate .sql files with pure SQL testing via harness
- **Config**: TOML format via Python's tomllib
- **Manifests**: TOML with SHA256 checksums, atomic writes
- **Data Access**: pyopensky's Trino connection with OAuth
- **Storage**: Local filesystem for v1
- **Tiles**: DuckDB → GeoJSON → Tippecanoe pipeline
- **Frontend**: MapLibre GL + vanilla JS + HTMX (no build step)
- **API**: Click CLI with embedded FastAPI
- **Testing**: pytest with real OpenSky samples + synthetic edge cases

## Phase Overview

0. **Foundation** — Config, logging, test harness → *Everything initializes correctly*
1. **Data Access** — OpenSky connection, auth, test data → *Can query and cache flight data*
2. **Extraction** — Monthly Parquet with manifests → *Raw data persisted locally*
3. **Segmentation** — Gap detection, interpolation, H3 coverage → *Flight paths identified*
4. **Incidents** — Emergency detection, debouncing → *Anomalies captured*
5. **Aggregation** — H3 cells, rates, coverage → *Statistics computed*
6. **Tiles** — PMTiles generation → *Map data ready*
7. **API** — Drill-down endpoint → *Details accessible*
8. **Frontend** — Interactive map → *Full visualization*
9. **Integration** — End-to-end validation → *Production ready*

## Checkbox Discipline

- **Task checkbox ☐**: Check only after successful red-green-refactor cycle
- **Phase checkbox ☐**: Check only after manual QC and git commit
- **Never check boxes for planned or in-progress work**

## How to Use This Document

1. Start at Phase 0 and work sequentially
2. For each task:
   - Read the requirements and reference `SPEC.md` sections
   - Write the RED test first
   - Implement minimal GREEN solution
   - REFACTOR for clarity and quality
   - Check the box only when complete
3. After completing all tasks in a phase:
   - Run full test suite
   - Run linting and type checking
   - Perform manual QC as specified
   - Commit with descriptive message
   - Check the phase box

---

## Phase 0: Project Foundation ☐

**Goal**: Establish project structure, configuration system, logging, and test framework.

**Outcome**: Configuration loads correctly, logging works, test harness runs, linting/typing passes.

**References**: SPEC §8.2 (Configuration), §8.3 (Logging), §7.1 (Testing)

### Tasks

- [ ] **Create project structure**
  - RED: Test that expected directories don't exist (`test_project_structure.py`)
  - GREEN: Create directories: `aviation_anomaly/`, `tests/`, `sql/`, `data/`, `static/`
  - GREEN: Create `__init__.py` files where needed
  - REFACTOR: Add `.gitignore` for data/, *.pyc, etc.
  - Note: This establishes our working environment

- [ ] **Implement TOML configuration loader**
  - RED: Test config loading fails when file missing
  - RED: Test invalid TOML raises clear error
  - RED: Test missing required fields caught
  - GREEN: Create `Config` class using `tomllib`
  - GREEN: Load from file path with error handling
  - REFACTOR: Add validation, defaults, type hints
  ```python
  # Example config structure to test:
  # [segments]
  # gap_minutes = 20
  ```

- [ ] **Set up structured logging**
  - RED: Test logger not configured initially
  - RED: Test log format is not JSON
  - GREEN: Create logger factory with JSON formatter
  - GREEN: Include fields: timestamp, level, message, stage, duration_ms
  - REFACTOR: Add context manager for operation timing
  - Test: `with log_operation("test"): pass` logs duration

- [ ] **Create SQL test harness**
  - RED: Test harness module doesn't exist
  - RED: Test can't execute SQL queries
  - GREEN: Implement harness to run .sql files against DuckDB
  - GREEN: Support comparing query results to expected outputs
  - GREEN: Install DuckDB extensions (spatial, h3)
  - REFACTOR: Add fixtures for test data, parameterized tests
  - Test: `SELECT 1 as num` returns `[(1,)]`

- [ ] **Initialize Click CLI structure**
  - RED: Test CLI entry point doesn't exist
  - RED: Test --config flag not recognized
  - GREEN: Create `cli.py` with basic Click app
  - GREEN: Add --config option with default path
  - GREEN: Connect to pyproject.toml entry point
  - REFACTOR: Add version, help text
  - Test: `aviation-anomaly --help` shows usage

- [ ] **Configure pytest with markers**
  - RED: Test markers not defined
  - RED: Test fixtures not available
  - GREEN: Update pytest.ini with unit/integration markers
  - GREEN: Create conftest.py with shared fixtures
  - GREEN: Add tmp_path fixtures for test isolation
  - REFACTOR: Add test utilities module
  - Test: `pytest -m unit` runs only unit tests

- [ ] **Set up linting and type checking**
  - RED: Code fails ruff formatting check
  - RED: Type annotations missing or incorrect
  - GREEN: Fix all ruff violations
  - GREEN: Add basic type hints to all functions
  - GREEN: Configure pre-commit hooks
  - REFACTOR: Fine-tune ruff/mypy rules
  - Test: `ruff check`, `mypy` pass without errors

**Manual QC Checklist**:
- [ ] Run `pytest` - all tests pass
- [ ] Run `ruff check` - no violations
- [ ] Run `mypy aviation_anomaly` - no errors
- [ ] Load sample config.toml successfully
- [ ] Verify JSON logs include all required fields
- [ ] SQL test harness executes sample query
- [ ] CLI help text is clear and complete

**Commit Message**: `feat: establish project foundation with config, logging, and test framework`

---

## Phase 1: Data Access Layer ☐

**Goal**: Establish OpenSky connection via pyopensky, implement OAuth authentication, acquire test data.

**Outcome**: Can authenticate and query OpenSky Trino, have 48-hour test dataset cached locally.

**References**: SPEC §3.1 (OpenSky access), §7.2 (Test data)

### Tasks

- [ ] **Implement OAuth authentication**
  - RED: Test auth fails without credentials
  - RED: Test invalid credentials raise specific error
  - GREEN: Implement OAuth flow using pyopensky
  - GREEN: Store tokens securely (not in git)
  - GREEN: Handle token acquisition and storage
  - REFACTOR: Add token caching and validation
  - Test: Valid credentials return access token
  - Note: May need manual browser flow for initial auth

- [ ] **Create Trino connection manager**
  - RED: Test connection fails without setup
  - RED: Test query fails with expired token
  - GREEN: Establish Trino connection via pyopensky
  - GREEN: Execute simple test query (`SELECT 1`)
  - GREEN: Handle connection timeouts gracefully
  - REFACTOR: Add connection pooling, retry logic
  - Test: Can query `states_history_data4` table structure

- [ ] **Implement token refresh mechanism**
  - RED: Test expired token not refreshed automatically
  - RED: Test refresh fails with invalid refresh token
  - GREEN: Detect token expiration
  - GREEN: Implement refresh flow
  - GREEN: Update stored tokens after refresh
  - REFACTOR: Add pre-emptive refresh before expiry
  - Test: Long-running queries don't fail due to token expiry

- [ ] **Build test data extractor**
  - RED: Test no data extraction capability
  - RED: Test extraction fails for invalid date range
  - GREEN: Query 1 hour of states data
  - GREEN: Scale to 48-hour extraction
  - GREEN: Save as Parquet with schema preservation
  - REFACTOR: Add progress reporting, chunking
  - Test: Extract 2024-01-01 00:00 to 2024-01-02 23:59
  - Note: Choose date range with known good data coverage

- [ ] **Create test data cache system**
  - RED: Test cache miss on first run
  - RED: Test cache invalidation needed
  - GREEN: Cache extracted data locally
  - GREEN: Implement cache key based on date range
  - GREEN: Verify cache integrity (row count, schema)
  - REFACTOR: Add cache expiration, size limits
  - Test: Second extraction uses cache, not Trino

- [ ] **Generate synthetic test data**
  - RED: Test no synthetic data generator
  - RED: Test edge cases not covered
  - GREEN: Create basic flight data generator
  - GREEN: Generate specific patterns:
    - Aircraft with 19-min gap (same segment)
    - Aircraft with 21-min gap (new segment)
    - Squawk 7700 for exactly 15 minutes
    - Multiple emergency squawks in sequence
  - REFACTOR: Make generators configurable, reproducible
  - Test: Synthetic data matches real data schema

- [ ] **Implement data validation**
  - RED: Test invalid data passes through
  - RED: Test schema mismatches not caught
  - GREEN: Validate required fields present
  - GREEN: Check data types and ranges
  - GREEN: Verify lat/lon validity
  - GREEN: Check temporal ordering
  - REFACTOR: Create reusable validators
  - Test: Invalid positions rejected, nulls handled

**Manual QC Checklist**:
- [ ] Successfully authenticate with OpenSky
- [ ] Query returns data from `states_history_data4`
- [ ] 48-hour test dataset cached in `data/test/`
- [ ] Test data has >1000 unique aircraft
- [ ] Synthetic data covers all edge cases
- [ ] Token refresh works during long query
- [ ] All data validation rules enforced

**Commit Message**: `feat: implement OpenSky data access layer with auth and test data`

---

## Phase 2: Data Extraction Pipeline (Stage-1) ☐

**Goal**: Implement monthly extraction from OpenSky to Parquet with TOML manifests, ensuring idempotency.

**Outcome**: Monthly Parquet files with validated manifests, idempotent execution, comprehensive data quality guards.

**References**: SPEC §4.1 (Stage-1 Extraction), §8.1 (Manifests)

### Tasks

- [ ] **Create extraction SQL queries**
  - RED: Test SQL file doesn't exist
  - RED: Test query missing required columns
  - GREEN: Write `sql/extraction/daily_states.sql`
  - GREEN: Select only required fields from SPEC §3.1
  - GREEN: Add WHERE clause for date range
  - REFACTOR: Optimize with appropriate hints/limits
  - Test: Query returns exactly the columns specified
  - Note: Keep query simple, filtering happens in Python

- [ ] **Implement daily data chunking**
  - RED: Test can't extract single day
  - RED: Test fails on invalid date
  - GREEN: Extract one day of data (UTC boundaries)
  - GREEN: Handle months with 28/29/30/31 days
  - GREEN: Process days sequentially to manage memory
  - REFACTOR: Add parallel processing with constraints
  - Test: February extraction handles leap years correctly

- [ ] **Build monthly union logic**
  - RED: Test can't combine daily chunks
  - RED: Test duplicate data not handled
  - GREEN: Union daily DataFrames into monthly
  - GREEN: Ensure no duplicate (icao24, time) pairs
  - GREEN: Maintain temporal ordering
  - REFACTOR: Optimize memory usage for large months
  - Test: 31 days union correctly for January

- [ ] **Apply data quality guards**
  - RED: Test invalid data passes through
  - RED: Test null positions not caught
  - GREEN: Reject rows with null lat/lon
  - GREEN: Reject |lat| > 90 or |lon| > 180
  - GREEN: Enforce monotonic time per aircraft
  - GREEN: Fail fast on any violation (no partial data)
  - REFACTOR: Create guard report before failing
  - Test: Single invalid row causes full extraction to abort

- [ ] **Implement Parquet writer with partitioning**
  - RED: Test can't write Parquet file
  - RED: Test wrong path structure
  - GREEN: Write to `data/raw/year=YYYY/month=MM/`
  - GREEN: Use snappy compression
  - GREEN: Preserve data types exactly
  - REFACTOR: Add schema validation after write
  - Test: Written file readable by DuckDB

- [ ] **Create TOML manifest system**
  - RED: Test no manifest created
  - RED: Test manifest missing required fields
  - GREEN: Generate manifest with all fields:
    - data_version, code_version
    - source_range (start/end timestamps)
    - row_counts (total and per day)
    - checksum (SHA256 of Parquet file)
    - config_hash (SHA256 of config.toml)
  - REFACTOR: Add manifest schema validation
  - Test: Checksum verifies correctly

- [ ] **Implement atomic writes**
  - RED: Test partial writes leave corrupt files
  - RED: Test concurrent writes conflict
  - GREEN: Write to temp files first
  - GREEN: Atomic rename only after success
  - GREEN: Clean up temp files on failure
  - REFACTOR: Add file locking mechanism
  - Test: Interrupted write doesn't corrupt existing data

- [ ] **Add idempotency checks**
  - RED: Test re-runs duplicate work
  - RED: Test can't detect existing data
  - GREEN: Check manifest before extraction
  - GREEN: Skip if data exists and config unchanged
  - GREEN: Re-run if config hash differs
  - REFACTOR: Add --force flag to override
  - Test: Second run skips extraction completely

**Manual QC Checklist**:
- [ ] Extract January 2024 successfully
- [ ] Manifest contains correct checksums
- [ ] Re-running extraction skips due to idempotency
- [ ] Invalid data causes immediate failure
- [ ] Parquet files readable in DuckDB
- [ ] File structure matches SPEC exactly
- [ ] Atomic writes prevent corruption

**Commit Message**: `feat: implement Stage-1 extraction pipeline with manifests and quality guards`

---

## Phase 3: Flight Segmentation ☐

**Goal**: Implement segment detection with gaps, interpolation, and H3 line coverage using DuckDB SQL.

**Outcome**: Flight segments with polylines, filtered by duration/distance, H3 cells assigned for all resolutions.

**References**: SPEC §4.2.1-4.2.2 (Segmentation), Appendix A (SQL examples)

### Tasks

- [ ] **Create gap detection SQL**
  - RED: Test SQL doesn't detect gaps
  - RED: Test wrong gap threshold
  - GREEN: Write `sql/segments/gap_detection.sql`
  - GREEN: Implement window functions per SPEC Appendix A
  - GREEN: Test exactly at boundaries:
    - 1199 seconds (19:59) → same segment
    - 1200 seconds (20:00) → new segment
    - 1201 seconds (20:01) → new segment
  - REFACTOR: Optimize window function performance
  - Test: First point always starts new segment

- [ ] **Build segment aggregation SQL**
  - RED: Test can't group by segments
  - RED: Test segment IDs not deterministic
  - GREEN: Write `sql/segments/segment_builder.sql`
  - GREEN: Group consecutive points by segment number
  - GREEN: Calculate segment_id as `hash(icao24 || start_time || end_time)`
  - GREEN: Collect path as array of [lat, lon, time]
  - REFACTOR: Add segment metadata (duration, distance)
  - Test: Same input always produces same segment_id

- [ ] **Implement duration/distance filters**
  - RED: Test all segments kept regardless of size
  - RED: Test OR logic instead of AND
  - GREEN: Write `sql/segments/filter_segments.sql`
  - GREEN: Remove if duration < 600s AND distance < 30km
  - GREEN: Test all combinations:
    - 540s + 25km → removed
    - 540s + 35km → kept
    - 660s + 25km → kept
    - 660s + 35km → kept
  - REFACTOR: Make thresholds configurable via params
  - Test: Single-point segments always filtered

- [ ] **Create great-circle interpolation**
  - RED: Test no interpolation between points
  - RED: Test H3 cells skipped on long legs
  - GREEN: Write `sql/segments/interpolate_paths.sql`
  - GREEN: Add points at max 10km chord distance
  - GREEN: Add points at max 60s time interval
  - GREEN: Use finer of the two constraints
  - GREEN: Preserve original points in output
  - REFACTOR: Optimize for large segments
  - Test: London-NYC flight has >50 interpolated points

- [ ] **Implement H3 line coverage**
  - RED: Test no H3 cells assigned
  - RED: Test cells missing along path
  - GREEN: Write `sql/segments/h3_line_cover.sql`
  - GREEN: Use h3-duckdb extension functions
  - GREEN: Generate cells for resolutions 3-7
  - GREEN: Store as arrays per resolution
  - REFACTOR: Batch H3 operations for performance
  - Test: No gaps in cell coverage along path

- [ ] **Apply segment-cell deduplication**
  - RED: Test segment counted multiple times per cell
  - RED: Test denominator inflated
  - GREEN: Write `sql/segments/deduplicate_cells.sql`
  - GREEN: Ensure segment contributes max 1 per cell
  - GREEN: Maintain this for all resolutions
  - REFACTOR: Use efficient DISTINCT operations
  - Test: Circular flight doesn't double-count cells

- [ ] **Add aircraft registry enrichment**
  - RED: Test no aircraft data joined
  - RED: Test join fails on missing aircraft
  - GREEN: Write `sql/segments/enrich_aircraft.sql`
  - GREEN: LEFT JOIN with aircraft registry
  - GREEN: Add registration, typecode, manufacturer
  - GREEN: Handle nulls gracefully
  - REFACTOR: Cache aircraft data in memory
  - Test: Unknown aircraft don't break pipeline

- [ ] **Create segment output writer**
  - RED: Test segments not persisted
  - RED: Test wrong output format
  - GREEN: Write segments to Parquet
  - GREEN: Path: `data/curated/segments/year=YYYY/month=MM/`
  - GREEN: Include all segment attributes
  - GREEN: Write manifest with checksums
  - REFACTOR: Optimize Parquet compression
  - Test: Segments readable by DuckDB

**Manual QC Checklist**:
- [ ] Gap detection works at exact 20-minute boundary
- [ ] Segment IDs are deterministic
- [ ] Duration/distance filter uses AND logic correctly
- [ ] Interpolation prevents H3 cell gaps
- [ ] All resolutions (3-7) have cell coverage
- [ ] Deduplication keeps denominator accurate
- [ ] Aircraft enrichment handles nulls
- [ ] Output Parquet has expected schema

**Commit Message**: `feat: implement flight segmentation with gap detection and H3 coverage`

---

## Phase 4: Incident Detection ☐

**Goal**: Detect emergency squawks, implement type-specific debouncing, track incident metadata.

**Outcome**: Incident records with proper debouncing, type classification, duration tracking, H3 cell assignment.

**References**: SPEC §4.2.3 (Incident Detection), Appendix A (Debounce SQL)

### Tasks

- [ ] **Create squawk detection SQL**
  - RED: Test no emergency squawks detected
  - RED: Test invalid squawks accepted
  - GREEN: Write `sql/incidents/detect_squawks.sql`
  - GREEN: Filter for squawks in {7500, 7600, 7700}
  - GREEN: Map codes to types:
    - 7500 → "unlawful_interference"
    - 7600 → "lost_comms"  
    - 7700 → "general_emergency"
  - REFACTOR: Add squawk validation (4-digit octal)
  - Test: Squawk 7701 ignored, 7700 detected

- [ ] **Implement incident state machine**
  - RED: Test state transitions not tracked
  - RED: Test incident boundaries wrong
  - GREEN: Write `sql/incidents/incident_states.sql`
  - GREEN: Track entry/exit from emergency states
  - GREEN: Create incident when entering {7500,7600,7700}
  - GREEN: End incident when leaving to normal
  - GREEN: Handle transitions between emergency types
  - REFACTOR: Optimize state tracking with window functions
  - Test: 7700→7600 creates two separate incidents

- [ ] **Apply type-specific debouncing**
  - RED: Test no debouncing applied
  - RED: Test different types merged incorrectly
  - GREEN: Write `sql/incidents/debounce_incidents.sql`
  - GREEN: Implement 15-minute (900s) debounce window
  - GREEN: Merge only same-type incidents:
    - 7700 at 00:00, 7700 at 00:14 → one incident
    - 7700 at 00:00, 7700 at 00:16 → two incidents
    - 7700 at 00:00, 7600 at 00:05 → two incidents
  - REFACTOR: Use efficient window functions
  - Test: Debounce logic per SPEC Appendix A

- [ ] **Calculate incident metrics**
  - RED: Test no duration calculated
  - RED: Test duration not capped
  - GREEN: Write `sql/incidents/incident_metrics.sql`
  - GREEN: Calculate duration_s = t_end - t_start
  - GREEN: Cap duration at 5400s (90 minutes) for stats
  - GREEN: Capture callsign_first (at incident start)
  - GREEN: Count affected segments
  - REFACTOR: Add incident severity indicators
  - Test: 2-hour incident shows duration_s = 5400

- [ ] **Join aircraft registry data**
  - RED: Test no aircraft data joined
  - RED: Test join breaks on missing aircraft
  - GREEN: Write `sql/incidents/enrich_incidents.sql`
  - GREEN: LEFT JOIN with aircraft registry on icao24
  - GREEN: Add registration, typecode, manufacturer
  - GREEN: Preserve incidents even if aircraft unknown
  - REFACTOR: Handle multiple registrations per icao24
  - Test: Unknown aircraft has null typecode

- [ ] **Map incidents to H3 cells**
  - RED: Test incidents not mapped to cells
  - RED: Test duration weighting applied
  - GREEN: Write `sql/incidents/incident_h3_mapping.sql`
  - GREEN: Assign incident to all cells segment touches
  - GREEN: No duration weighting (count = 1 per cell)
  - GREEN: Map for all resolutions (3-7)
  - REFACTOR: Optimize spatial joins
  - Test: Long incident doesn't get extra weight

- [ ] **Generate incident identifiers**
  - RED: Test no incident IDs generated
  - RED: Test IDs not unique
  - GREEN: Write `sql/incidents/incident_ids.sql`
  - GREEN: Create deterministic incident_id
  - GREEN: Format: `hash(segment_id || type || t_start)`
  - GREEN: Ensure globally unique IDs
  - REFACTOR: Add human-readable ID prefix
  - Test: Same incident always gets same ID

- [ ] **Create incident output writer**
  - RED: Test incidents not persisted
  - RED: Test wrong schema output
  - GREEN: Write incidents to Parquet
  - GREEN: Path: `data/curated/incidents/year=YYYY/month=MM/`
  - GREEN: Include all required fields per SPEC
  - GREEN: Write manifest with checksums
  - REFACTOR: Optimize for query performance
  - Test: Incidents joinable with segments

**Manual QC Checklist**:
- [ ] All emergency squawks detected correctly
- [ ] State transitions create proper incidents
- [ ] 15-minute debounce works per type
- [ ] Duration capped at 90 minutes
- [ ] Aircraft data enrichment handles nulls
- [ ] H3 mapping has no duration bias
- [ ] Incident IDs are deterministic
- [ ] Output schema matches SPEC §4.2.3

**Commit Message**: `feat: implement incident detection with type-specific debouncing`

---

## Phase 5: H3 Aggregation ☐

**Goal**: Aggregate segments and incidents to H3 cells, calculate rates, assign coverage notes.

**Outcome**: H3 aggregates with flight counts, incident rates in PPM, coverage assessments for all resolutions.

**References**: SPEC §4.3 (Aggregation), Appendix A (Aggregation SQL)

### Tasks

- [ ] **Calculate flight denominator**
  - RED: Test no flight counting
  - RED: Test segments double-counted
  - GREEN: Write `sql/aggregation/flight_denominator.sql`
  - GREEN: COUNT(DISTINCT segment_id) per cell
  - GREEN: Ensure deduplication works:
    - Segment crossing cell twice = count 1
    - Two segments in cell = count 2
  - REFACTOR: Optimize DISTINCT operations
  - Test: Circular route doesn't inflate denominator

- [ ] **Aggregate incident counts**
  - RED: Test no incident aggregation
  - RED: Test wrong incident assignment
  - GREEN: Write `sql/aggregation/incident_counts.sql`
  - GREEN: Count total incidents per cell
  - GREEN: Count by type (7500, 7600, 7700)
  - GREEN: No duration weighting (each = 1)
  - REFACTOR: Efficient GROUP BY with FILTER clause
  - Test: Multi-cell incident counted in each cell

- [ ] **Calculate rates in PPM**
  - RED: Test no rate calculation
  - RED: Test division by zero not handled
  - GREEN: Write `sql/aggregation/calculate_rates.sql`
  - GREEN: rate_all_ppm = incidents_all / flights * 1,000,000
  - GREEN: Return NULL if flights = 0
  - GREEN: Calculate per-type rates too
  - REFACTOR: Add rate bounds checking
  - Test: 2 incidents, 1000 flights = 2000 PPM

- [ ] **Compute coverage metrics**
  - RED: Test no coverage assessment
  - RED: Test wrong threshold logic
  - GREEN: Write `sql/aggregation/coverage_metrics.sql`
  - GREEN: Calculate median points_per_flight per cell
  - GREEN: Coverage note logic:
    - "Good": points_per_flight ≥ 4 AND flights ≥ 100
    - "Partial": otherwise (but flights ≥ 50)
    - "Mask": flights < 50
  - REFACTOR: Use window functions for efficiency
  - Test: 49 flights → Mask, 100 flights + 5 pts → Good

- [ ] **Identify top aircraft types**
  - RED: Test no aircraft type analysis
  - RED: Test considering all segments
  - GREEN: Write `sql/aggregation/top_aircraft.sql`
  - GREEN: Find mode of typecodes from incident segments only
  - GREEN: Break ties by count, then alphabetically
  - GREEN: Handle NULLs (unknown aircraft)
  - REFACTOR: Optimize mode calculation
  - Test: A320 (5), B737 (5) → A320 wins alphabetically

- [ ] **Generate multi-resolution aggregates**
  - RED: Test single resolution only
  - RED: Test resolutions calculated separately
  - GREEN: Write `sql/aggregation/multi_resolution.sql`
  - GREEN: Process resolutions 3-7 in one pass
  - GREEN: Maintain consistent counts across resolutions
  - GREEN: Parent cells should logically contain children
  - REFACTOR: Parallelize resolution processing
  - Test: r3 cell contains sum of its r4 children

- [ ] **Apply masking rules**
  - RED: Test no masking applied
  - RED: Test statistics shown for sparse cells
  - GREEN: Write `sql/aggregation/apply_masking.sql`
  - GREEN: Set all metrics to NULL if flights < 50
  - GREEN: Keep cell in output but mark as masked
  - GREEN: Preserve coverage_note = "Mask"
  - REFACTOR: Make threshold configurable
  - Test: 45 flights → all metrics NULL except coverage_note

- [ ] **Create aggregate output writer**
  - RED: Test aggregates not persisted
  - RED: Test wrong file structure
  - GREEN: Write aggregates to Parquet
  - GREEN: Path: `data/aggregates/res=r{r}/aggregates_YYYYMM.parquet`
  - GREEN: Include all metrics per SPEC §4.3
  - GREEN: Write manifest with checksums
  - REFACTOR: Optimize for tile generation queries
  - Test: Aggregates readable by tile builder

**Manual QC Checklist**:
- [ ] Denominator correctly deduplicated
- [ ] Incident counts accurate per type
- [ ] Rates calculated in PPM with NULL handling
- [ ] Coverage notes follow exact thresholds
- [ ] Top aircraft from incidents only
- [ ] All resolutions (3-7) processed
- [ ] Masking applied below 50 flights
- [ ] Output schema matches SPEC §4.3

**Commit Message**: `feat: implement H3 aggregation with rates and coverage assessment`

---

## Phase 6: Tile Generation ☐

**Goal**: Convert H3 aggregates to PMTiles via DuckDB → GeoJSON → Tippecanoe pipeline.

**Outcome**: Valid PMTiles files per resolution with preserved attributes, proper zoom levels, size optimization.

**References**: SPEC §4.4 (Tile Build), §5.4 (Zoom→H3 mapping)

### Tasks

- [ ] **Create H3 to geometry converter**
  - RED: Test can't convert H3 to polygons
  - RED: Test invalid geometries produced
  - GREEN: Write `sql/tiles/h3_to_geometry.sql`
  - GREEN: Use h3_cell_to_boundary_wkt() function
  - GREEN: Convert H3 indices to polygon WKT
  - GREEN: Handle pentagons correctly (12 per resolution)
  - REFACTOR: Optimize batch conversions
  - Test: H3 index 8928308280fffff produces valid hexagon

- [ ] **Build GeoJSON export SQL**
  - RED: Test no GeoJSON export capability
  - RED: Test missing required properties
  - GREEN: Write `sql/tiles/export_geojson.sql`
  - GREEN: Structure as FeatureCollection
  - GREEN: Include all attributes from SPEC §4.4:
    - month, h3_res, h3_index
    - flights, incidents_all, incidents_7500/7600/7700
    - rate_all_ppm, top_aircraft_typecode
    - coverage_note
  - REFACTOR: Minimize coordinate precision
  - Test: Valid GeoJSON with all properties

- [ ] **Implement DuckDB GDAL export**
  - RED: Test can't write GeoJSON file
  - RED: Test CRS not set correctly
  - GREEN: Use COPY TO with FORMAT GDAL
  - GREEN: Set DRIVER='GeoJSON'
  - GREEN: Specify EPSG:4326 projection
  - GREEN: Handle NULL values properly
  - REFACTOR: Optimize for large datasets
  - Test: Output readable by geojson.io

- [ ] **Create Tippecanoe wrapper**
  - RED: Test can't invoke Tippecanoe
  - RED: Test wrong parameters used
  - GREEN: Subprocess call with proper arguments:
    - `-o output.pmtiles` (output file)
    - `-l hotspots_r{r}` (layer name)
    - `--minimum-zoom=4 --maximum-zoom=12`
    - `--no-tile-size-limit` (initially)
  - GREEN: Capture stdout/stderr for debugging
  - REFACTOR: Add error handling and retries
  - Test: PMTiles file created successfully

- [ ] **Configure zoom-dependent settings**
  - RED: Test all zooms show same resolution
  - RED: Test wrong resolution at zoom levels
  - GREEN: Implement zoom→H3 mapping from SPEC §5.4:
    - z4-5 → r3
    - z6-7 → r4
    - z8-9 → r5
    - z10-11 → r6
    - z12+ → r7
  - GREEN: Set appropriate simplification per zoom
  - REFACTOR: Make zoom mapping configurable
  - Test: Zoom 6 shows r4 hexagons

- [ ] **Optimize tile size**
  - RED: Test tiles exceed 200KB regularly
  - RED: Test over-simplification loses data
  - GREEN: Add Tippecanoe optimization flags:
    - `--simplification=10` (adjust as needed)
    - `--drop-densest-as-needed`
    - Quantize coordinates appropriately
  - GREEN: Monitor tile sizes
  - REFACTOR: Balance size vs quality
  - Test: 95% of tiles under 200KB

- [ ] **Generate multi-month PMTiles**
  - RED: Test single month only
  - RED: Test months in separate files
  - GREEN: Combine multiple months in one PMTiles
  - GREEN: Ensure month attribute preserved
  - GREEN: Handle large temporal ranges
  - REFACTOR: Optimize for time-based queries
  - Test: Can filter by month attribute

- [ ] **Create TileJSON metadata**
  - RED: Test no metadata file
  - RED: Test metadata out of sync
  - GREEN: Generate TileJSON with:
    - Bounds, center, min/max zoom
    - Attribution text
    - Available months list
    - Layer names and properties
  - REFACTOR: Auto-generate from PMTiles
  - Test: TileJSON validates against schema

- [ ] **Validate PMTiles output**
  - RED: Test no validation performed
  - RED: Test corrupt files accepted
  - GREEN: Verify PMTiles structure
  - GREEN: Check all attributes present
  - GREEN: Validate zoom level content
  - GREEN: Test with pmtiles CLI tool
  - REFACTOR: Add comprehensive checks
  - Test: PMTiles readable by MapLibre

**Manual QC Checklist**:
- [ ] H3 cells convert to valid polygons
- [ ] GeoJSON exports with all attributes
- [ ] Tippecanoe processes without errors
- [ ] Zoom levels show correct H3 resolutions
- [ ] Tile sizes mostly under 200KB
- [ ] Multiple months in single PMTiles
- [ ] TileJSON metadata accurate
- [ ] PMTiles render in map viewer

**Commit Message**: `feat: implement tile generation pipeline with PMTiles output`

---

## Phase 7: API Backend ☐

**Goal**: Implement FastAPI drill-down endpoint within Click CLI application.

**Outcome**: REST API serving incident details per cell with filtering, pagination, proper error handling.

**References**: SPEC §6.2 (Drill-down API), §5.2 (UX Requirements)

### Tasks

- [ ] **Create FastAPI application structure**
  - RED: Test no FastAPI app exists
  - RED: Test app doesn't initialize
  - GREEN: Create basic FastAPI application
  - GREEN: Add CORS middleware for browser access
  - GREEN: Configure JSON response formatting
  - GREEN: Add OpenAPI documentation
  - REFACTOR: Organize into modules
  - Test: GET /docs shows API documentation

- [ ] **Implement drill-down endpoint**
  - RED: Test endpoint doesn't exist
  - RED: Test wrong URL pattern
  - GREEN: Create `/api/drilldown` endpoint
  - GREEN: Define query parameters:
    - month: str (YYYY-MM format)
    - h3_res: int (3-7)
    - h3_index: str (hex string)
    - sq: str (all|7500|7600|7700)
    - limit: int (max 200, default 200)
    - offset: int (default 0)
  - REFACTOR: Use Pydantic models for validation
  - Test: Endpoint responds to valid request

- [ ] **Add parameter validation**
  - RED: Test invalid parameters accepted
  - RED: Test no validation errors
  - GREEN: Validate month format (YYYY-MM)
  - GREEN: Validate h3_res in range 3-7
  - GREEN: Validate h3_index is valid hex
  - GREEN: Validate sq in allowed values
  - GREEN: Enforce limit ≤ 200
  - REFACTOR: Create reusable validators
  - Test: Invalid month returns 400 error

- [ ] **Build DuckDB query layer**
  - RED: Test can't query Parquet files
  - RED: Test wrong data returned
  - GREEN: Query incidents Parquet directly
  - GREEN: Filter by month, cell, squawk
  - GREEN: Apply pagination (LIMIT/OFFSET)
  - GREEN: Sort by timestamp_start DESC
  - REFACTOR: Use prepared statements
  - Test: Query returns expected incidents

- [ ] **Implement response formatting**
  - RED: Test wrong response structure
  - RED: Test missing required fields
  - GREEN: Format response per SPEC:
    ```json
    {
      "meta": {"month": "...", "h3_res": ..., "h3_index": "...", "count": ...},
      "rows": [...]
    }
    ```
  - GREEN: Include all incident fields
  - REFACTOR: Use response models
  - Test: Response matches schema exactly

- [ ] **Add error handling**
  - RED: Test errors crash server
  - RED: Test generic 500 errors
  - GREEN: Return 404 for missing data
  - GREEN: Return 400 for invalid params
  - GREEN: Return 500 with error details
  - GREEN: Log errors with context
  - REFACTOR: Create error response models
  - Test: Missing month returns proper 404

- [ ] **Optimize query performance**
  - RED: Test slow queries >300ms
  - RED: Test no query optimization
  - GREEN: Add DuckDB connection pooling
  - GREEN: Cache Parquet metadata
  - GREEN: Use column projection
  - GREEN: Add query execution timing
  - REFACTOR: Pre-filter Parquet files
  - Test: 95% of queries under 300ms

- [ ] **Integrate with Click CLI**
  - RED: Test no CLI command exists
  - RED: Test server doesn't start
  - GREEN: Add `aviation-anomaly serve` command
  - GREEN: Accept --host and --port options
  - GREEN: Start FastAPI with uvicorn
  - GREEN: Handle graceful shutdown
  - REFACTOR: Add --reload for development
  - Test: CLI starts server successfully

- [ ] **Add request logging**
  - RED: Test no request tracking
  - RED: Test missing performance metrics
  - GREEN: Log all requests with timing
  - GREEN: Include query parameters
  - GREEN: Track response size
  - GREEN: Monitor error rates
  - REFACTOR: Structured logging format
  - Test: Logs show request details

**Manual QC Checklist**:
- [ ] API documentation accessible at /docs
- [ ] All parameters validated correctly
- [ ] Pagination works with correct totals
- [ ] Error responses have proper status codes
- [ ] Query performance under 300ms
- [ ] Server starts/stops cleanly via CLI
- [ ] Concurrent requests handled properly
- [ ] Response format matches SPEC exactly

**Commit Message**: `feat: implement drill-down API with FastAPI and Click integration`

---

## Phase 8: Frontend Application ☐

**Goal**: Build interactive map with MapLibre GL, HTMX controls, and drill-down display.

**Outcome**: Responsive web map showing hotspots with full interactivity, no build step required.

**References**: SPEC §5 (Frontend), §5.2 (UX Requirements), §5.3 (Performance Budgets)

### Tasks

- [ ] **Create HTML structure**
  - RED: Test no HTML file exists
  - RED: Test invalid HTML5 structure
  - GREEN: Create `static/index.html`
  - GREEN: Add semantic HTML5 elements:
    - `<header>` with title
    - `<main>` with map container
    - `<aside>` for controls and drill-down
  - GREEN: Include viewport meta for mobile
  - REFACTOR: Optimize for performance
  - Test: HTML validates with W3C validator

- [ ] **Initialize MapLibre GL map**
  - RED: Test map doesn't render
  - RED: Test wrong map configuration
  - GREEN: Load MapLibre GL from CDN
  - GREEN: Initialize map with:
    - Container: 'map'
    - Style: basic basemap
    - Center: [0, 20] (Atlantic)
    - Zoom: 3 (global view)
  - GREEN: Add navigation controls
  - REFACTOR: Make config data-driven
  - Test: Map renders without errors

- [ ] **Add PMTiles source and protocol**
  - RED: Test can't load PMTiles
  - RED: Test protocol handler missing
  - GREEN: Load PMTiles protocol library
  - GREEN: Register protocol handler
  - GREEN: Add source for each resolution:
    ```javascript
    map.addSource('hotspots-r4', {
      type: 'vector',
      url: 'pmtiles://tiles/h3_r4/hotspots.pmtiles'
    });
    ```
  - REFACTOR: Dynamic source loading
  - Test: Tiles fetch via range requests

- [ ] **Implement hex rendering with colors**
  - RED: Test hexagons don't appear
  - RED: Test wrong color mapping
  - GREEN: Add fill layer for hexagons
  - GREEN: Implement hybrid color scale:
    - Grey for masked cells (<50 flights)
    - Gradient for rates (green→yellow→red)
    - Quantile-based for high values
  - GREEN: Apply zoom-based visibility
  - REFACTOR: Make color scale configurable
  - Test: Hexagons colored by rate_all_ppm

- [ ] **Create interactive legend**
  - RED: Test no legend present
  - RED: Test legend doesn't explain colors
  - GREEN: Build legend with:
    - Color gradient bar
    - Rate labels (PPM)
    - "Insufficient data" grey
    - Coverage note explanation
  - GREEN: Make legend responsive
  - REFACTOR: Generate from data
  - Test: Legend matches map colors

- [ ] **Add HTMX filter controls**
  - RED: Test no filter controls
  - RED: Test filters don't work
  - GREEN: Create filter form with HTMX:
    - Month selector (dropdown)
    - Squawk type (All/7500/7600/7700)
    - Resolution lock (advanced)
  - GREEN: Use `hx-trigger` for updates
  - GREEN: Update map without refresh
  - REFACTOR: Add loading indicators
  - Test: Filters update map instantly

- [ ] **Implement hover tooltips**
  - RED: Test no hover feedback
  - RED: Test tooltip missing data
  - GREEN: Show tooltip on hex hover:
    - Rate (PPM)
    - Flight count
    - Incident counts (total and by type)
    - Top aircraft type
    - Coverage note
  - GREEN: Position tooltip near cursor
  - REFACTOR: Optimize hover performance
  - Test: Tooltip shows all attributes

- [ ] **Build drill-down panel**
  - RED: Test click does nothing
  - RED: Test panel doesn't show
  - GREEN: Open panel on hex click
  - GREEN: Fetch details via HTMX:
    ```html
    <div hx-get="/api/drilldown?..." 
         hx-trigger="hexclick">
    ```
  - GREEN: Display incident table
  - GREEN: Add sorting and pagination
  - REFACTOR: Smooth animations
  - Test: Panel shows incident details

- [ ] **Add CSV export**
  - RED: Test no export capability
  - RED: Test wrong data exported
  - GREEN: Add export button to drill-down
  - GREEN: Convert table data to CSV
  - GREEN: Trigger download with:
    ```javascript
    blob = new Blob([csv], {type: 'text/csv'});
    ```
  - GREEN: Name file with cell ID and month
  - REFACTOR: Handle special characters
  - Test: CSV contains all visible rows

- [ ] **Ensure accessibility**
  - RED: Test no keyboard navigation
  - RED: Test poor color contrast
  - GREEN: Add ARIA labels to controls
  - GREEN: Enable keyboard navigation
  - GREEN: Use color-blind safe palette
  - GREEN: Add skip links
  - GREEN: Test with screen reader
  - REFACTOR: Follow WCAG guidelines
  - Test: Lighthouse accessibility score >90

- [ ] **Optimize performance**
  - RED: Test slow initial load >2s
  - RED: Test janky interactions
  - GREEN: Lazy load PMTiles
  - GREEN: Debounce hover events
  - GREEN: Use CSS transforms for animations
  - GREEN: Minimize repaints
  - REFACTOR: Add service worker caching
  - Test: Initial render <2s on 4G

**Manual QC Checklist**:
- [ ] Map loads globally at zoom 3
- [ ] PMTiles fetch only visible tiles
- [ ] Hexagons render with correct colors
- [ ] Legend explains color scheme
- [ ] Filters update map via HTMX
- [ ] Tooltips show on hover
- [ ] Click opens drill-down panel
- [ ] CSV export works correctly
- [ ] Keyboard navigation functional
- [ ] Performance budget met (<2s load)

**Commit Message**: `feat: implement frontend with MapLibre GL and HTMX controls`

---

## Phase 9: Integration & Deployment ☐

**Goal**: Validate end-to-end pipeline, create automation scripts, prepare for production deployment.

**Outcome**: Full pipeline runs successfully, all acceptance criteria met, system ready for production use.

**References**: SPEC §7.2-7.4 (Integration Tests), §8 (Operations), Appendix B (Acceptance Checklist)

### Tasks

- [ ] **Create pipeline orchestrator**
  - RED: Test no orchestration exists
  - RED: Test stages run out of order
  - GREEN: Write `run_pipeline.py` using Click
  - GREEN: Define stage dependencies:
    - Stage 1 (extraction) → Stage 2 (segments)
    - Stage 2 → Stage 3 (incidents)
    - Stage 3 → Stage 4 (aggregation)
    - Stage 4 → Stage 5 (tiles)
  - GREEN: Check manifests before each stage
  - REFACTOR: Add parallel execution where possible
  - Test: Pipeline stops on first failure

- [ ] **Implement mini-month testing**
  - RED: Test no integration test data
  - RED: Test full month takes too long
  - GREEN: Create 48-hour test dataset
  - GREEN: Run all stages on mini-month
  - GREEN: Verify outputs at each stage:
    - Raw Parquet exists
    - Segments generated
    - Incidents detected
    - Aggregates calculated
    - Tiles created
  - REFACTOR: Make test data reproducible
  - Test: Mini-month pipeline <5 minutes

- [ ] **Add manifest validation**
  - RED: Test manifests not checked
  - RED: Test corrupt data accepted
  - GREEN: Verify manifest checksums
  - GREEN: Check row counts reasonable
  - GREEN: Validate schema compliance
  - GREEN: Compare config hashes
  - REFACTOR: Create manifest validator tool
  - Test: Modified file detected by checksum

- [ ] **Create performance benchmarks**
  - RED: Test no performance tracking
  - RED: Test budgets exceeded silently
  - GREEN: Measure stage durations
  - GREEN: Check performance budgets:
    - Map load <2s on 4G
    - API response <300ms
    - Tile size <200KB typical
  - GREEN: Log all metrics
  - REFACTOR: Add performance regression tests
  - Test: Slow operations flagged

- [ ] **Build deployment package**
  - RED: Test can't deploy system
  - RED: Test missing dependencies
  - GREEN: Create deployment structure:
    ```
    aviation-anomaly/
    ├── aviation_anomaly/  (Python package)
    ├── sql/               (SQL files)
    ├── static/            (Frontend)
    ├── config.toml        (Configuration)
    └── requirements.txt   (Dependencies)
    ```
  - GREEN: Include all necessary files
  - REFACTOR: Add Docker option
  - Test: Fresh install works

- [ ] **Write operational scripts**
  - RED: Test no operational tools
  - RED: Test manual processes only
  - GREEN: Create utility scripts:
    - `check_health.py` - System health
    - `validate_data.py` - Data integrity
    - `backup_data.py` - Backup critical data
    - `restore_data.py` - Restore from backup
  - REFACTOR: Add to CLI commands
  - Test: Scripts executable and documented

- [ ] **Validate acceptance criteria**
  - RED: Test criteria unchecked
  - RED: Test incomplete validation
  - GREEN: Check each item from SPEC Appendix B:
    - [ ] Stage-1 writes monthly Parquet
    - [ ] Segments match gap/duration rules
    - [ ] Incidents debounced at 15 min
    - [ ] Aggregates honor mask rule
    - [ ] PMTiles pass size validation
    - [ ] Frontend renders r4 globally
    - [ ] Drill-down API returns correctly
    - [ ] Documentation complete
  - REFACTOR: Automate checklist validation
  - Test: All criteria demonstrably met

- [ ] **Create user documentation**
  - RED: Test no user docs
  - RED: Test docs don't work
  - GREEN: Write comprehensive README:
    - System overview
    - Installation steps
    - Configuration guide
    - Running the pipeline
    - Troubleshooting
  - GREEN: Add inline code comments
  - REFACTOR: Add architecture diagrams
  - Test: New user can run system

- [ ] **Implement monitoring hooks**
  - RED: Test no observability
  - RED: Test silent failures
  - GREEN: Add logging throughout
  - GREEN: Create metrics collection:
    - Pipeline run status
    - Stage durations
    - Error counts
    - Data volumes
  - GREEN: Export to JSON/stdout
  - REFACTOR: Add OpenTelemetry support
  - Test: Metrics accessible and accurate

- [ ] **Perform load testing**
  - RED: Test system untested at scale
  - RED: Test performance degradation
  - GREEN: Run with full month data
  - GREEN: Test concurrent API requests
  - GREEN: Verify tile serving at scale
  - GREEN: Check memory usage
  - REFACTOR: Optimize bottlenecks
  - Test: System handles expected load

**Manual QC Checklist**:
- [ ] Complete pipeline runs without errors
- [ ] Mini-month test passes in <5 minutes
- [ ] All manifests validate correctly
- [ ] Performance budgets met
- [ ] Deployment package complete
- [ ] Acceptance criteria satisfied
- [ ] Documentation clear and accurate
- [ ] Monitoring shows system health
- [ ] Load tests pass successfully
- [ ] System ready for production

**Commit Message**: `feat: complete integration testing and deployment preparation`

---

## Final Sign-off

**All phases complete**: The Aviation Anomaly Tracker is ready for production deployment. The system successfully:

1. ✅ Extracts OpenSky flight data
2. ✅ Detects and analyzes emergency incidents  
3. ✅ Aggregates to H3 hexagonal grid
4. ✅ Generates optimized map tiles
5. ✅ Serves drill-down details via API
6. ✅ Displays interactive global hotspot map
7. ✅ Meets all performance requirements
8. ✅ Passes comprehensive testing

**Next Steps**:
- Deploy to production environment
- Monitor initial usage
- Gather user feedback
- Plan v2 enhancements (per SPEC §10)
