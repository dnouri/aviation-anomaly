#!/usr/bin/env bash
# Test script to verify Makefile dependency tracking works correctly
# without actually regenerating expensive data files.
#
# Strategy:
# 1. Use `make -n` (dry-run) to see what WOULD be rebuilt
# 2. Touch code files to simulate changes
# 3. Verify the correct cascade of dependencies
#
# This tests our dependency DECLARATIONS, not Make itself.
# Make is battle-tested; we just need to verify we declared dependencies correctly.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "═══════════════════════════════════════════════════════════════"
echo "Makefile Dependency Testing (Dry-Run Mode)"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "This script tests dependency tracking WITHOUT regenerating data."
echo "It uses 'make -n' to show what WOULD be rebuilt."
echo ""

# Test 1: Changing segmentation SQL should rebuild everything downstream
echo -e "${YELLOW}Test 1: Changing segmentation.sql${NC}"
echo "Expected: segments → incidents → h3 → geojson → pmtiles"
echo ""
echo "Strategy: Delete one segment file to simulate staleness"
echo ""

# Backup and remove one segment file
SEGMENT_FILE="data/segments/segments_2025-07-02.parquet"
SEGMENT_BACKUP="/tmp/test_segment_backup.parquet"

if [ -f "$SEGMENT_FILE" ]; then
    cp "$SEGMENT_FILE" "$SEGMENT_BACKUP"
    rm "$SEGMENT_FILE"

    # Check what Make would rebuild
    REBUILD_OUTPUT=$(make -n pipeline-geojson 2>&1 || true)

    # Restore file
    mv "$SEGMENT_BACKUP" "$SEGMENT_FILE"

    # Verify expected rebuilds
    if echo "$REBUILD_OUTPUT" | grep -q "segment.*2025-07-02"; then
        echo -e "${GREEN}✓ Would rebuild segments${NC}"
    else
        echo -e "${RED}✗ Would NOT rebuild segments (FAIL)${NC}"
    fi

    if echo "$REBUILD_OUTPUT" | grep -q "detect.*2025-07-02"; then
        echo -e "${GREEN}✓ Would rebuild incidents${NC}"
    else
        echo -e "${RED}✗ Would NOT rebuild incidents (FAIL)${NC}"
    fi

    if echo "$REBUILD_OUTPUT" | grep -q "aggregate.*--resolutions"; then
        echo -e "${GREEN}✓ Would rebuild H3${NC}"
    else
        echo -e "${RED}✗ Would NOT rebuild H3 (FAIL)${NC}"
    fi

    if echo "$REBUILD_OUTPUT" | grep -q "tiles.*--h3-dir"; then
        echo -e "${GREEN}✓ Would rebuild GeoJSON${NC}"
    else
        echo -e "${RED}✗ Would NOT rebuild GeoJSON (FAIL)${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Segment file doesn't exist, skipping test${NC}"
fi

echo ""

# Test 2: Deleting H3 file should rebuild H3 and GeoJSON, but NOT segments
echo -e "${YELLOW}Test 2: Missing H3 file triggers rebuild${NC}"
echo "Expected: h3 → geojson (but NOT segments/incidents)"
echo ""
echo "Strategy: Delete one H3 file to simulate staleness"
echo ""

H3_FILE="data/h3/h3_incidents_r3.parquet"
H3_BACKUP="/tmp/test_h3_backup.parquet"

if [ -f "$H3_FILE" ]; then
    cp "$H3_FILE" "$H3_BACKUP"
    rm "$H3_FILE"

    REBUILD_OUTPUT=$(make -n pipeline-geojson 2>&1 || true)

    # Restore file
    mv "$H3_BACKUP" "$H3_FILE"

    if echo "$REBUILD_OUTPUT" | grep -q "segment.*2025-07-02"; then
        echo -e "${RED}✗ Would rebuild segments (FAIL - should skip)${NC}"
    else
        echo -e "${GREEN}✓ Would skip segments${NC}"
    fi

    if echo "$REBUILD_OUTPUT" | grep -q "aggregate.*--resolutions"; then
        echo -e "${GREEN}✓ Would rebuild H3${NC}"
    else
        echo -e "${RED}✗ Would NOT rebuild H3 (FAIL)${NC}"
    fi

    if echo "$REBUILD_OUTPUT" | grep -q "tiles.*--h3-dir"; then
        echo -e "${GREEN}✓ Would rebuild GeoJSON${NC}"
    else
        echo -e "${RED}✗ Would NOT rebuild GeoJSON (FAIL)${NC}"
    fi
else
    echo -e "${YELLOW}⚠ H3 file doesn't exist, skipping test${NC}"
fi

echo ""

# Test 3: Deleting GeoJSON file should rebuild only GeoJSON, not H3
echo -e "${YELLOW}Test 3: Missing GeoJSON file triggers rebuild${NC}"
echo "Expected: geojson (but NOT segments/incidents/h3)"
echo ""
echo "Strategy: Delete one GeoJSON file to simulate staleness"
echo ""

GEOJSON_FILE="data/tiles/geojsonl/h3_r3.geojsonl.gz"
GEOJSON_BACKUP="/tmp/test_geojson_backup.geojsonl.gz"

if [ -f "$GEOJSON_FILE" ]; then
    cp "$GEOJSON_FILE" "$GEOJSON_BACKUP"
    rm "$GEOJSON_FILE"

    REBUILD_OUTPUT=$(make -n pipeline-geojson 2>&1 || true)

    # Restore file
    mv "$GEOJSON_BACKUP" "$GEOJSON_FILE"

    if echo "$REBUILD_OUTPUT" | grep -q "aggregate.*--resolutions"; then
        echo -e "${RED}✗ Would rebuild H3 (FAIL - should skip)${NC}"
    else
        echo -e "${GREEN}✓ Would skip H3${NC}"
    fi

    if echo "$REBUILD_OUTPUT" | grep -q "tiles.*--h3-dir"; then
        echo -e "${GREEN}✓ Would rebuild GeoJSON${NC}"
    else
        echo -e "${RED}✗ Would NOT rebuild GeoJSON (FAIL)${NC}"
    fi
else
    echo -e "${YELLOW}⚠ GeoJSON file doesn't exist, skipping test${NC}"
fi

echo ""

echo "═══════════════════════════════════════════════════════════════"
echo "Test Summary"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "✓ These tests verify Make's dependency DECLARATIONS are correct"
echo ""
echo "Limitation: make -n (dry-run) cannot predict future timestamps."
echo "When testing SQL code changes, we delete output files to simulate"
echo "staleness, since touching SQL doesn't trigger rebuilds in dry-run"
echo "(Make sees current timestamps, not predicted future timestamps)."
echo ""
echo "For comprehensive testing with actual execution:"
echo ""
echo "  # Test with minimal dataset (1 date × 1 resolution)"
echo "  make PIPELINE_DATES='2025-07-02' PIPELINE_RESOLUTIONS='3' pipeline-all"
echo ""
echo "  # Touch SQL file and verify rebuilds happen"
echo "  touch aviation_anomaly/sql/segmentation.sql"
echo "  make PIPELINE_DATES='2025-07-02' PIPELINE_RESOLUTIONS='3' pipeline-segments"
echo ""
echo "  # Verify timestamps changed"
echo "  stat -c '%y %n' data/segments/segments_2025-07-02.parquet"
echo ""
