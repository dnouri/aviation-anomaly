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

**Goal**: Build flight segments from raw position data with gap detection and interpolation.

**Outcome**: Flight segments with polylines, ready for H3 cell coverage computation.

**References**: SPEC §4.2.1 (Segment Builder)

### Tasks

- [ ] **Implement gap detection logic**
  - RED: Test segment breaks at 20+ minute gap
  - RED: Test segment continues at 19 minute gap
  - GREEN: Group positions by icao24, order by time
  - GREEN: Start new segment when gap > 20 minutes
  - GREEN: Compute segment_id as hash(icao24, start_time, end_time)
  - REFACTOR: Optimize with window functions
  - Test: Verify correct segment boundaries

- [ ] **Filter short segments**
  - RED: Test short segments not filtered
  - GREEN: Discard segments with duration < 10 min AND distance < 30 km
  - GREEN: Compute great-circle distance for segment
  - REFACTOR: Use DuckDB spatial functions
  - Test: Edge cases at exactly 10 min / 30 km

- [ ] **Interpolate segment polylines**
  - RED: Test no interpolation between points
  - GREEN: Interpolate at max 10 km chord or 60s interval
  - GREEN: Use great-circle interpolation
  - GREEN: Store as polyline for H3 coverage
  - REFACTOR: Optimize interpolation algorithm
  - Test: No H3 cell skips in coverage

- [ ] **Create segment output schema**
  - RED: Test segment schema missing
  - GREEN: Define Parquet schema for segments
  - GREEN: Include all fields from SPEC §4.2.1
  - GREEN: Write to data/curated/segments/
  - REFACTOR: Add schema validation
  - Test: Schema matches specification

**Manual QC Checklist**:
- [ ] Segments break correctly at gaps
- [ ] Short segments filtered properly
- [ ] Interpolation produces smooth paths
- [ ] Output files have correct schema
- [ ] Performance acceptable for daily data

---

## Summary of Changes

### What We Accomplished
1. ✅ **Simplified Authentication**: Removed complex OAuth flows, using password auth only
2. ✅ **Clean Architecture**: One module per concern (auth.py, data_access.py, config.py)
3. ✅ **Elegant Token Management**: Automatic caching and refresh in `.opensky_tokens.json`
4. ✅ **Test Coverage**: All authentication paths tested with proper mocks
5. ✅ **Documentation**: Clear README with setup instructions

### Key Technical Decisions
- **Password Authentication Only**: OpenSky Trino doesn't support OAuth client credentials
- **Local Token Cache**: `.opensky_tokens.json` in current directory (not home folder)
- **Environment Variables**: `OPENSKY_USERNAME` and `OPENSKY_PASSWORD` for CI/CD
- **Correct Table**: `minio.osky.state_vectors_data4` (not `states_history_data4`)
- **Partition Strategy**: Hour partitions only (no day partition), query full day range
- **DuckDB Streaming**: Handle ~500M rows/day without loading into memory
- **No Pandas**: Direct Trino → DuckDB → Parquet pipeline
- **No pyopensky**: Direct Trino connection instead of external library
- **Config Simplicity**: Business logic only in config.toml, no auth settings

### Next Steps
Continue with Phase 2 (Data Extraction) when ready, focusing on:
1. Extracting test data from OpenSky
2. Building data cache system
3. Creating synthetic test data for edge cases
4. Implementing the full extraction pipeline

**Ready for commit with message**: `feat: implement OpenSky password authentication with token management`
