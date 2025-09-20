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
- **Data Access**: OpenSky Trino with password authentication (JWT tokens)
- **Storage**: Local filesystem for v1
- **Tiles**: DuckDB → GeoJSON → Tippecanoe pipeline
- **Frontend**: MapLibre GL + vanilla JS + HTMX (no build step)
- **API**: Click CLI with embedded FastAPI
- **Testing**: pytest with real OpenSky samples + synthetic edge cases

## Phase Overview

0. **Foundation** ✅ — Config, logging, test harness → *Everything initializes correctly*
1. **Data Access** ✅ — OpenSky connection, auth, test data → *Can query and cache flight data*
2. **Extraction** ✅ — Daily/hourly Parquet with resume → *Raw data persisted locally*
3. **Segmentation** ✅ — Gap detection, interpolation, H3 coverage → *Flight paths identified*
4. **Incidents** ✅ — Emergency detection, debouncing → *Anomalies captured*
5. **Aggregation** ☐ — H3 cells, rates, coverage → *Statistics computed*
6. **Tiles** ☐ — PMTiles generation → *Map data ready*
7. **API** ☐ — Drill-down endpoint → *Details accessible*
8. **Frontend** ☐ — Interactive map → *Full visualization*
9. **Integration** ☐ — End-to-end validation → *Production ready*

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

## Phase 0: Project Foundation ✅

**Goal**: Establish project structure, configuration system, logging, and test framework.

**Outcome**: Configuration loads correctly, logging works, test harness runs, linting/typing passes.

**References**: SPEC §8.2 (Configuration), §8.3 (Logging), §7.1 (Testing)

### Tasks

- [x] **Create project structure**
- [x] **Implement TOML configuration loader**
- [x] **Set up structured logging**
- [x] **Create SQL test utilities with qck**
- [x] **Initialize Click CLI structure**
- [x] **Configure pytest with markers and fixtures**
- [x] **Set up linting and type checking**

**Manual QC Checklist**:
- [x] Run `pytest` - all tests pass (22 tests)
- [x] Run `ruff check` - no violations
- [x] Load sample config.toml successfully
- [x] Verify JSON logs include all required fields
- [x] SQL test harness executes sample query (via sql_runner fixture)
- [x] CLI help text is clear and complete

**Commit Message**: `feat: establish project foundation with config, logging, and test framework`

---

## Phase 1: Data Access Layer ✅

**Goal**: Establish OpenSky connection with password authentication, implement token management.

**Outcome**: Can authenticate and query OpenSky Trino using password flow with automatic token caching.

**References**: SPEC §3.1 (OpenSky access), §7.2 (Test data)

### Key Decisions Made:
- **Authentication**: OpenSky Trino requires password authentication (not OAuth client credentials)
- **Token Management**: JWT tokens cached in `.opensky_tokens.json` in current directory
- **Token Lifecycle**: 2-hour access tokens, 10-hour refresh tokens, automatic refresh
- **Credential Sources**: Environment variables (`OPENSKY_USERNAME`/`OPENSKY_PASSWORD`) or interactive prompts

### Tasks

- [x] **Implement password authentication**
  - RED: Test auth fails without credentials ✓
  - RED: Test CI mode requires env vars ✓
  - GREEN: Detect environment (CI vs interactive) ✓
  - GREEN: Password grant flow for JWT tokens ✓
  - GREEN: Token cache at `.opensky_tokens.json` (0600 perms) ✓
  - GREEN: Automatic token refresh with 5-minute buffer ✓
  - REFACTOR: Create TokenManager and CredentialProvider classes ✓
  - Test: CI mode works with env vars ✓
  - Test: Interactive mode prompts for credentials ✓
  - Test: Token refresh happens automatically ✓

- [x] **Create Trino query connection**
  - RED: Test can't query without auth ✓
  - RED: Test query fails with invalid SQL ✓
  - GREEN: Establish Trino connection using JWT from password auth ✓
  - GREEN: Execute test query against OpenSky data ✓
  - GREEN: Connection reuse for efficiency ✓
  - REFACTOR: Clean public API with `TrinoQueryEngine` ✓
  - Test: Can query real OpenSky tables ✓
  - Test: Token caching reduces auth time ✓

**Manual QC Checklist**:
- [x] Successfully authenticate with OpenSky (password flow working)
- [x] Tokens cached securely with 0600 permissions
- [x] CI mode detects environment variables correctly
- [x] Interactive mode prompts when no env vars
- [x] Token refresh works automatically
- [x] Query returns data from OpenSky tables
- [x] Cached token used on subsequent runs (fast response)

**Commit Message**: `feat: implement OpenSky password authentication with token management`

---

## Phase 2: Data Extraction Pipeline (Stage-1) ✅

**Goal**: Implement daily/monthly extraction from OpenSky to Parquet with resumable downloads.

**Outcome**: Daily and hourly Parquet files with resumable extraction, optimized performance.

**Data Status**: Successfully extracted 7 days (July 1-7, 2025) comprising 5.1 billion records across 109K unique aircraft.

**References**: SPEC §4.1 (Stage-1 Extraction)

### Key Achievements:
- **Performance**: 160x speedup (from 310s to 1.9s for 1M rows) using PyArrow zero-copy
- **Resumability**: Smart resume at both daily and hourly levels
- **Reliability**: Automatic retry with exponential backoff for rate limiting
- **Efficiency**: Direct streaming via DuckDB without intermediate storage

### Tasks

- [x] **Create extraction SQL queries**
  - RED: Test query missing required columns ✓
  - GREEN: Query `minio.osky.state_vectors_data4` with hour partitions ✓
  - GREEN: Select required fields: time, icao24, callsign, lat, lon, squawk, onground, alert ✓
  - GREEN: Filter nulls (lat/lon required) ✓
  - REFACTOR: Order by time for efficient processing ✓

- [x] **Implement hourly data extraction**
  - RED: Test can't extract single hour ✓
  - GREEN: Extract one hour using partition predicate ✓
  - GREEN: Stream via DuckDB directly to Parquet ✓
  - GREEN: Atomic writes with .tmp files ✓
  - REFACTOR: Add rate limiting retry logic ✓

- [x] **Implement daily data extraction**
  - RED: Test can't extract single day ✓
  - RED: Test fails on invalid date ✓
  - GREEN: Extract 24 hours with progress bar ✓
  - GREEN: Consolidate hourly files to daily ✓
  - GREEN: Resume from existing hourly files ✓
  - GREEN: Skip if daily file exists (new) ✓
  - REFACTOR: Add force_redownload flag ✓

- [x] **Implement date range extraction**
  - RED: Test range extraction missing ✓
  - GREEN: Extract multiple days sequentially ✓
  - GREEN: Progress tracking for days ✓
  - REFACTOR: Pass through resume logic ✓

- [x] **Optimize performance**
  - RED: Test performance <10s for 1M rows ✓
  - GREEN: Initial DuckDB UNNEST approach (4s) ✓
  - GREEN: PyArrow zero-copy integration (1.9s) ✓
  - REFACTOR: Remove batching, simplify progress ✓
  - Test: 160x speedup verified ✓

- [x] **Add CLI commands**
  - RED: Test extract command missing ✓
  - GREEN: --date for single day ✓
  - GREEN: --date-range for multiple days ✓
  - GREEN: --no-resume to force re-download ✓
  - GREEN: --output-dir for data location ✓
  - REFACTOR: Clear help text and examples ✓

**Manual QC Checklist**:
- [x] Extract 2025-01-01 successfully (millions of rows)
- [x] Resume works: re-run skips completed hours
- [x] Daily file check: skips entire day if exists
- [x] Performance: 1M rows in <2 seconds
- [x] Rate limiting handled gracefully
- [x] All 36 tests pass

**Commit Messages**:
- `feat: implement hourly and daily extraction from OpenSky`
- `perf: optimize extraction with PyArrow zero-copy (160x speedup)`
- `feat: add daily file resume logic for efficient re-runs`

---

## Phase 3: Flight Segmentation ✅

**Goal**: Build flight segments from raw position data with gap detection and distance filtering.

**Outcome**: Pure SQL-based segmentation pipeline with memory-safe execution for billion-row processing.

**Implementation Evolution**:
1. Initial: Python-based FlightSegmenter with DataFrame operations (caused OOM)
2. Final: Single SQL file (segment_pipeline.sql) with streaming CTEs via qck

**Critical Bug Fixed**:
- ORDER BY in ARRAY_AGG caused 741M row memory explosion (non-spillable state)
- Solution: Removed ORDER BY, data pre-sorted in raw_data CTE
- Result: Successfully processed 730M+ rows with 4GB RAM limit

**Final Architecture**:
- Single mega-query: `segment_pipeline.sql` (155 lines)
- Python orchestrator: `segmentation.py` (124 lines, no DataFrames)
- Memory config: SET statements at query start
- Atomic writes: temp file + rename pattern

**References**: SPEC §4.2 (Transformation), §4.5 (SQL Methodology)

### Completed Tasks ✅

- [x] **SQL-based gap detection**
  - Implemented in segment_pipeline.sql using LAG window functions
  - Gap threshold: ≥1200 seconds (20 minutes)
  - Tests: Exact boundaries at 1199/1200/1201 seconds

- [x] **Distance calculation and filtering**
  - Haversine formula in SQL (no PostGIS needed)
  - OR condition: keep if duration ≥600s OR distance ≥30km
  - Tests: All 7 boundary combinations validated

- [x] **Interpolation (deferred to v1.1)**
  - Too complex for pure SQL approach
  - Not needed for v1 gap-based segmentation
  - Documented in SPEC.md as future enhancement

- [x] **Squawk coverage tracking**
  - list_filter/list_count operations (not UNNEST)
  - Handles NULL vs empty string squawks correctly
  - Tests: 0%, 33%, 47%, 100% coverage scenarios

- [x] **Memory-safe configuration**
  - DuckDB settings in config.toml
  - 4GB memory limit, 100GB temp space
  - Tests: Runs with 100MB limit successfully

**Test Coverage Added**:
- [x] 13 new tests in test_segmentation_sql.py
- [x] Boundary value testing (exact thresholds)
- [x] NULL squawk handling (35% of real data)
- [x] Single-point segments (edge case)
- [x] Unordered input data (ORDER BY verification)
- [x] Total: 56 tests passing (was 43)

**Manual QC Completed**:
- [x] All 56 tests passing
- [x] Linting and type checking clean
- [x] SQL file tested with 730M+ rows
- [x] Documentation updated (SPEC.md §4.5)

**Commit Message**: `refactor: implement SQL-based segmentation with comprehensive testing`

---

## Phase 4: Incident Detection with Quality Gates ✅

**Goal**: Detect emergency squawks with quality validation to filter spurious signals.

**Outcome**: SQL-based incident detection pipeline with quality gates and confidence scoring.

**Implementation**: Single SQL file (incident_detection.sql) following memory-safe patterns from Phase 3.

**Quality Gates Implemented**:
1. **Temporal**: 5+ samples within 60 seconds
2. **Persistence**: Emergency must last >45 seconds
3. **Airborne**: <30% of samples on ground
4. **Confidence**: Minimum score of 50

**Architecture**:
- Pure SQL pipeline: `incident_detection.sql` (241 lines)
- Python orchestrator: `incident_detection.py` (178 lines)
- Memory-safe CTEs with list operations
- Atomic writes with temp file pattern

**References**: SPEC §4.2.2-4.2.3 (Quality Gates & Incident Detection)

### Completed Tasks ✅

- [x] **Implement temporal quality gates**
  - Tests: 4 samples fail, 5 samples pass
  - 60-second window validation
  - Persistence >45 seconds required
  - Ground ratio <30% validation
  - All gates combined in SQL CTEs

- [x] **Build confidence scoring system**
  - Base score from sample count (max 40 points)
  - Persistence bonus (5-30 points based on duration)
  - Airborne bonus (10-20 points based on ground %)
  - Roller-dial penalty (-10 points if detected)
  - Categories: HIGH/MEDIUM/LOW

- [x] **Detect roller-dial transitions**
  - Pattern detection for 77XX codes (not 7700/7777)
  - Flag incidents with roller-dial patterns
  - Reduce confidence for suspected false positives

- [x] **Implement incident detection**
  - Process only segments with emergency squawks
  - Apply all quality gates sequentially
  - Track confidence and coverage metrics
  - Window functions for efficient processing

- [x] **Apply debouncing logic**
  - Merge incidents within 15 minutes (900s)
  - Group-based aggregation approach
  - Preserve maximum confidence scores
  - Duration cap at 90 minutes (5400s)

**Test Coverage**:
- [x] 9 new tests for incident detection
- [x] Temporal gate boundary testing
- [x] Persistence validation tests
- [x] Ground ratio filtering
- [x] Full pipeline integration test
- [x] Debouncing merge validation

**Manual QC Completed**:
- [x] All 66 tests passing
- [x] Memory-safe for large datasets
- [x] CLI command integrated (`aviation-anomaly detect`)
- [x] Statistics and analysis functions

**Commit Message**: `feat: implement incident detection with quality gates and SQL pipeline`

---

## Phase 5: H3 Aggregation with Dual Metrics ☐

**Goal**: Aggregate segments and incidents to H3 cells with proper metrics.

**Outcome**: H3 aggregates with coverage, confidence, and dual incident metrics.

**References**: SPEC §4.3 (Aggregation)

### Tasks

- [ ] **Compute H3 coverage from segments**
  - RED: Test coverage computation missing
  - GREEN: Use h3_line with coordinate arrays
  - GREEN: Generate coverage for r3-r7
  - GREEN: Track unique segments per cell
  - REFACTOR: Batch processing by resolution
  - Test: Coverage consistency across resolutions

- [ ] **Implement dual incident metrics**
  - RED: Test single metric insufficient
  - GREEN: Count incidents_unique (for rates)
  - GREEN: Count incidents_coverage (for heatmap)
  - GREEN: Calculate both rate types
  - Test: Verify metric differences

- [ ] **Calculate coverage quality (points-per-flight only)**
  - RED: Test missing coverage metrics
  - GREEN: Points per flight median as sole indicator
  - GREEN: Categories: Excellent(≥10), Good(6-9), Limited(3-5), Poor(<3)
  - GREEN: No composite scoring needed
  - Test: Category thresholds meaningful

- [ ] **Apply visibility thresholds**
  - RED: Test sparse cells not masked
  - GREEN: Resolution-scaled thresholds
  - GREEN: Confidence categories
  - GREEN: Mask below thresholds
  - Test: Each resolution independently

- [ ] **Generate aggregation outputs**
  - RED: Test output schema invalid
  - GREEN: Create resolution-specific Parquet
  - GREEN: Include all metrics and categories
  - GREEN: Write manifests
  - Test: Schema validation

**Manual QC Checklist**:
- [ ] Hotspots align with known patterns
- [ ] Coverage scores reflect data quality
- [ ] Dual metrics show expected differences
- [ ] Resolution scaling appropriate

---

## Phase 6: Tile Generation ☐

**Goal**: Generate PMTiles for map visualization.

**Outcome**: Resolution-specific PMTiles with all metrics.

**References**: SPEC §4.4 (Tile Build)

### Tasks

- [ ] **Export H3 cells to GeoJSON**
  - RED: Test GeoJSON export missing
  - GREEN: DuckDB ST_AsGeoJSON for cells
  - GREEN: Include all aggregation metrics
  - GREEN: Resolution-specific exports
  - Test: Valid GeoJSON structure

- [ ] **Generate PMTiles with Tippecanoe**
  - RED: Test PMTiles generation fails
  - GREEN: Configure Tippecanoe parameters
  - GREEN: Set appropriate zoom levels
  - GREEN: Optimize tile size (<200KB)
  - Test: Tile size and attribute validation

- [ ] **GDAL validation smoke test**
  - RED: Test GDAL can't read PMTiles
  - GREEN: Verify GDAL/OGR support
  - GREEN: Check attribute preservation
  - Test: CI integration

**Commit Message**: `feat: implement PMTiles generation for map visualization`

---

## Phase 7: API Development ☐

**Goal**: Create drill-down API for incident details.

**Outcome**: FastAPI endpoints embedded in Click CLI.

**References**: SPEC §6 (APIs)

### Tasks

- [ ] **Implement drill-down endpoint**
  - RED: Test endpoint not found
  - GREEN: Query incidents by cell/period
  - GREEN: Include quality metadata
  - GREEN: Pagination support
  - Test: Response format validation

- [ ] **Add export capabilities**
  - RED: Test CSV export missing
  - GREEN: Generate CSV with full metadata
  - GREEN: Size limits (max 200 rows)
  - Test: CSV format validation

**Commit Message**: `feat: add drill-down API with FastAPI`

---

## Phase 8: Frontend Implementation ☐

**Goal**: Create interactive map with proper user guidance.

**Outcome**: MapLibre GL map with coverage communication.

**References**: SPEC §5 (Frontend)

### Tasks

- [ ] **Implement base map with PMTiles**
  - RED: Test map doesn't load
  - GREEN: MapLibre GL with PMTiles protocol
  - GREEN: Resolution-based tile loading
  - Test: Performance benchmarks

- [ ] **Add coverage communication**
  - RED: Test missing disclaimers
  - GREEN: Persistent header warning
  - GREEN: Enhanced legend with confidence
  - GREEN: Coverage quality overlay
  - Test: User comprehension

- [ ] **Implement filters and controls**
  - RED: Test filters don't work
  - GREEN: Squawk type selector
  - GREEN: Time period selector
  - GREEN: Coverage overlay toggle
  - Test: Filter state management

- [ ] **Create drill-down interface**
  - RED: Test drill-down missing
  - GREEN: Click handler for cells
  - GREEN: Side panel with details
  - GREEN: CSV export button
  - Test: Data accuracy

**Commit Message**: `feat: implement interactive map with coverage guidance`

---

## Phase 9: Integration & Documentation ☐

**Goal**: End-to-end validation and learnings documentation.

**Outcome**: Production-ready system with documented insights.

**References**: SPEC §10.1 (Lessons Learned)

### Tasks

- [ ] **Run full pipeline on 7-day dataset**
  - Process all stages end-to-end
  - Measure performance at each stage
  - Document bottlenecks
  - Validate output quality

- [ ] **Document prototype learnings**
  - Validated vs invalidated assumptions
  - Performance benchmarks
  - Quality gate effectiveness
  - Coverage patterns observed

- [ ] **Create v2 prioritization**
  - Based on prototype findings
  - Technical debt inventory
  - Feature value assessment
  - Implementation roadmap

**Manual QC Checklist**:
- [ ] All 7 days processed successfully
- [ ] Map shows expected patterns
- [ ] Drill-down returns accurate data
- [ ] Performance meets targets
- [ ] Documentation complete

**Commit Message**: `feat: complete aviation anomaly tracker prototype`

---

## Key Architecture Decisions

### Data Pipeline
- **7-day prototype** instead of months (data availability)
- **Pure SQL pipelines** via qck for memory-safe processing
- **Quality gates** to filter spurious emergency signals
- **Dual metrics** for accurate rate calculation
- **Coverage scoring** for transparency

### Development Approach
- **1-hour sample** for rapid iteration
- **Three-layer testing** (synthetic + real + statistical)
- **Progressive scaling** (sample → day → week)
- **TDD discipline** throughout

### User Communication
- **Persistent disclaimers** about data limitations
- **Confidence visualization** via opacity
- **Coverage overlay** for data quality
- **Regional context** in documentation

### Technical Stack
- **DuckDB** with list operations (no spatial extensions needed yet)
- **Parquet** for segment storage (STRUCT arrays, not GeoParquet)
- **qck** for SQL template execution
- **PMTiles** for tile delivery (future)
- **MapLibre GL** for visualization (future)
- **FastAPI** embedded in Click CLI (future)

---

## Data Reality Acknowledgments

### Available Data (7 days, July 1-7, 2025)
- 5.1 billion records from 109K unique aircraft
- Fields: time, icao24, callsign, lat, lon, squawk, onground, alert
- ~35% records have NULL squawk (normal for ADS-B)
- ~2% records have NULL callsign

### Key Mitigations for Missing Data
- **No receiver diversity** → Stronger temporal validation (5+ samples)
- **No velocity/heading** → Interpolation deferred to v1.1 (not needed for gap-based segmentation)
- **Partial squawk coverage** → Process only observable, track coverage ratios
- **No altitude** → Focus on lateral patterns only

### Accepted Trade-offs
- Interpolation complexity deferred (gap-based segmentation sufficient for v1)
- Confidence scoring instead of receiver validation
- Single coverage metric (points-per-flight) instead of composite
- Document all limitations transparently

## Next Immediate Step

Phase 5: Implement H3 aggregation with dual metrics for visualization preparation.
