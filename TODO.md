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
3. **Segmentation** ☐ — Gap detection, interpolation, H3 coverage → *Flight paths identified*
4. **Incidents** ☐ — Emergency detection, debouncing → *Anomalies captured*
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

## Phase 3: Flight Segmentation ☐

**Goal**: Build flight segments from raw position data with gap detection, interpolation, and quality validation.

**Outcome**: Hybrid GeoParquet segments with both geometry and coordinate arrays for flexible processing.

**Data Strategy**:
- Development: 1-hour sample (July 1, 00:00 UTC) - 30M records
- Validation: Full day (July 1) - 730M records
- Production: 7 days (July 1-7) - 5.1B records

**Storage Design**: Hybrid GeoParquet with dual representation (geometry + arrays)

**References**: SPEC §4.2 (Transformation)

### Setup Tasks

- [ ] **Install DuckDB spatial extension**
  - Install and load spatial extension
  - Verify GeoParquet support
  - Test ST_Distance_Spheroid and ST_MakeLine functions

- [ ] **Create 1-hour development sample**
  - Extract first hour from July 1 daily file
  - Verify ~30M records, ~5K aircraft
  - Document that ~35% missing squawk is normal
  - Create test fixture from 10 representative aircraft

### Core Segmentation Tasks

- [ ] **Implement gap detection with window functions**
  - RED: Test fails at 19:59 gap (continues segment)
  - RED: Test passes at 20:00 gap (breaks segment)
  - GREEN: LAG() window to compute time deltas
  - GREEN: Flag new segments when delta > 1200 seconds
  - GREEN: Generate segment_id from icao24+timestamps
  - REFACTOR: Optimize partitioning strategy
  - Test: Synthetic boundary cases + real aircraft

- [ ] **Filter short segments with spatial functions**
  - RED: Test 9min + 29km segment filtered
  - RED: Test 11min + 31km segment kept
  - GREEN: ST_Distance_Spheroid for accurate distance
  - GREEN: Apply AND condition for filtering
  - REFACTOR: Index optimization for performance
  - Test: All boundary combinations

- [ ] **Implement dense interpolation (5km/30s)**
  - RED: Test H3 coverage has gaps without interpolation
  - GREEN: Calculate implied velocity from consecutive positions
  - GREEN: Validate implied velocity <1000 km/h (data quality)
  - GREEN: Dense interpolation at 5km OR 30s (whichever is denser)
  - GREEN: Build ST_MakeLine geometry for GIS
  - GREEN: Maintain coordinate array for H3
  - REFACTOR: Accept 3-4x processing time for correctness
  - Test: No H3 gaps, reasonable processing time

- [ ] **Create hybrid GeoParquet schema with coverage tracking**
  - RED: Test missing dual representation
  - GREEN: Define schema with geometry + arrays
  - GREEN: Add squawk_coverage_ratio field
  - GREEN: Track observable vs total samples
  - GREEN: Write GeoParquet with spatial metadata
  - REFACTOR: Add validation for both representations
  - Test: Verify QGIS can read geometry, H3 can use arrays

### Statistical Validation

- [ ] **Implement statistical tests**
  - Expected segments/day: 10K-20K
  - Duration distribution: median 1-2 hours
  - Coverage per segment: 50-200 H3 cells at r5
  - Alert on outliers for manual inspection

**Manual QC Checklist**:
- [ ] 1-hour sample: <30 seconds processing (dense interpolation)
- [ ] Full day: <15 minutes processing (3-4x overhead accepted)
- [ ] Segments visible in QGIS with correct paths
- [ ] H3 coverage has no gaps due to conservative interpolation
- [ ] Statistical ranges match expectations
- [ ] Squawk coverage ratios properly calculated
- [ ] Golden test aircraft match manual verification

**Commit Message**: `feat: implement flight segmentation with hybrid GeoParquet storage`

---

## Phase 4: Incident Detection with Quality Gates ☐

**Goal**: Detect emergency squawks with quality validation to filter spurious signals.

**Outcome**: High-quality incident dataset with confidence scoring.

**References**: SPEC §4.2.2-4.2.3 (Quality Gates & Incident Detection)

### Tasks

- [ ] **Implement temporal quality gates**
  - RED: Test 4 samples fails quality gate
  - RED: Test ground vehicle fails (>30% ground)
  - GREEN: Require 5+ consecutive samples in 60s window
  - GREEN: Require signal persistence >45 seconds
  - GREEN: Require ≤30% ground samples
  - REFACTOR: Create composable quality functions
  - Test: Each gate independently + combined

- [ ] **Build confidence scoring system**
  - RED: Test confidence score calculation
  - GREEN: Temporal stability weight (40%)
  - GREEN: Signal persistence weight (30%)
  - GREEN: Airborne ratio weight (20%)
  - GREEN: Squawk coverage weight (10%)
  - GREEN: Categories: High(>70), Medium(40-70), Low(<40)
  - Test: Score ranges and category boundaries

- [ ] **Detect roller-dial transitions**
  - RED: Test 7703→7700 detected as spurious
  - GREEN: Pattern matching for 77XX→7700
  - GREEN: Flag and filter transitions
  - Test: Various transition patterns

- [ ] **Implement incident detection (observable squawks only)**
  - RED: Test NULL squawks are skipped
  - RED: Test incident not detected without quality pass
  - GREEN: Process only ~65% of data with squawks
  - GREEN: Detect start/end of quality-validated squawks
  - GREEN: Track confidence scores and coverage ratios
  - GREEN: Require >30% squawk coverage for eligibility
  - REFACTOR: Optimize with window functions
  - Test: Real aircraft with known emergencies

- [ ] **Apply debouncing logic**
  - RED: Test 14-minute gap not merged
  - RED: Test 15-minute gap merged
  - GREEN: Merge same-type incidents <15 min apart
  - GREEN: Preserve quality scores
  - Test: Complex multi-incident scenarios

**Manual QC Checklist**:
- [ ] Known false positives filtered
- [ ] Real emergencies preserved
- [ ] Quality scores meaningful
- [ ] Ground incidents suppressed

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
- **Hybrid GeoParquet** for flexible spatial operations
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
- **DuckDB** with spatial and H3 extensions
- **GeoParquet** for segment storage
- **PMTiles** for tile delivery
- **MapLibre GL** for visualization
- **FastAPI** embedded in Click CLI

---

## Data Reality Acknowledgments

### Available Data (7 days, July 1-7, 2025)
- 5.1 billion records from 109K unique aircraft
- Fields: time, icao24, callsign, lat, lon, squawk, onground, alert
- ~35% records have NULL squawk (normal for ADS-B)
- ~2% records have NULL callsign

### Key Mitigations for Missing Data
- **No receiver diversity** → Stronger temporal validation (5+ samples)
- **No velocity/heading** → Dense 5km/30s interpolation
- **Partial squawk coverage** → Process only observable, track coverage ratios
- **No altitude** → Focus on lateral patterns only

### Accepted Trade-offs
- 3-4x processing time for correctness (dense interpolation)
- Confidence scoring instead of receiver validation
- Single coverage metric (points-per-flight) instead of composite
- Document all limitations transparently

## Next Immediate Step

Start Phase 3 with 1-hour sample extraction and segmentation development.
