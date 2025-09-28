# TODO: Squawk Filtering Implementation

## Overview
Implement configuration-driven squawk filtering using SQL parameters only. No Python post-processing.

## Tasks

### 1. Configuration Schema ✅
- [x] Add FilterProfile class to config.py
- [x] Add profiles dict to IncidentConfig
- [x] Add default_profile field to IncidentConfig
- [x] Create production profile with P75/P50 thresholds
- [x] Create research profile with P90 thresholds
- [x] Create high_security profile with strict thresholds
- [x] Write tests for new config schema
- [x] Update config.toml with filter profiles

### 2. SQL Template Updates ✅
- [x] Add filter parameter placeholders to incident_detection.sql
- [x] Add statistical outlier filters (max_samples per type)
- [x] Add temporal coherence filter (min_duration)
- [x] Add ensemble minimum filters (min_samples per type)
- [x] Update confidence threshold to be parameterized
- [x] Test SQL with various parameter combinations

### 3. Incident Detection Updates ✅
- [x] Add filter_profile parameter to detect_incidents()
- [x] Load filter profile from config
- [x] Transform profile to SQL parameters
- [x] Pass parameters to qck template
- [x] Remove any hardcoded thresholds (removed line 198)
- [x] Write tests for parameter passing
- [x] Test with each profile type

### 4. CLI Integration ✅
- [x] Add --filter-profile option to detect command
- [x] Add --list-profiles flag to show available profiles
- [x] Set default profile from config
- [x] Update help text with profile descriptions
- [x] Write CLI tests for new options

### 5. Update Existing Tests ✅
- [x] Update test fixtures with filter parameters
- [x] Modify tests that expect unfiltered counts
- [x] Add parametrized tests for different profiles
- [x] Ensure all tests pass with default profile
- [x] Add integration test with real data

### 6. Code Cleanup ✅
- [x] Remove any dead code from incident_detection.py
- [x] Remove hardcoded confidence threshold (line 198)
- [x] Ensure consistent parameter naming
- [x] Remove unused imports
- [x] Update docstrings to mention filtering

### 7. Validation & Documentation ✅
- [x] Run full test suite
- [x] Test with July 2, 2025 data
- [x] Verify incident counts match expectations
- [x] Update README.md with filter profile info
- [x] Document thresholds in SPEC.md

## Progress Log

### Session Start
- Starting implementation with configuration schema
- Following red-green-refactor TDD approach

### Implementation Complete ✅
- All filter profiles implemented and tested
- Tests passing (186/186 unit tests)
- Successfully tested with July 2, 2025 data:
  - No filter: 51/48/50 (149 total)
  - Research: 36/31/33 (100 total, -33%)
  - Production: 13/12/11 (36 total, -76%)
  - High Security: 1/0/0 (1 total, -99%)
- 7500 hijack incidents reduced from 51 to reasonable levels

---
