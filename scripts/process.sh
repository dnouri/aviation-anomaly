#!/bin/bash
# Low-Memory Processing Script - Processes days one at a time
# For systems with limited RAM (30GB) processing 10-12GB files

set -o pipefail

# ═══════════════════════════════════════════════════════════════
# LOGGING SETUP - Re-exec with tee if not already logging
# ═══════════════════════════════════════════════════════════════
if [ -z "$PIPELINE_LOG_FILE" ]; then
    # First execution - set up logging
    mkdir -p logs
    export PIPELINE_LOG_FILE="logs/process_$(date +"%Y%m%d_%H%M%S").log"

    echo "📝 Starting pipeline with logging to: ${PIPELINE_LOG_FILE}"
    echo "   You can monitor progress in another terminal with:"
    echo "   tail -f ${PIPELINE_LOG_FILE}"
    echo ""

    # Re-exec this script with tee for dual output
    exec "$0" "$@" 2>&1 | tee -a "${PIPELINE_LOG_FILE}"
fi

# ═══════════════════════════════════════════════════════════════
# MAIN PIPELINE - Only runs after re-exec with logging
# ═══════════════════════════════════════════════════════════════

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║         LOW-MEMORY AVIATION PROCESSING PIPELINE             ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo

export CONFIG_FILE="config.toml"

echo -e "${YELLOW}⚠️  Using configuration: ${CONFIG_FILE}${NC}"
echo -e "${YELLOW}   Memory limit: Check config.toml for current setting${NC}"
echo -e "${YELLOW}   Batch size: 2000${NC}"
echo

# Monitor memory usage
echo -e "${BLUE}📊 Current Memory Status:${NC}"
free -h | head -3
echo

# Clean swap if needed
if [ $(free | awk '/^Swap:/ {print int($3/$2*100)}') -gt 50 ]; then
    echo -e "${YELLOW}⚠️  High swap usage detected. Consider clearing swap:${NC}"
    echo -e "   sudo swapoff -a && sudo swapon -a"
    echo
fi

# Process days ONE AT A TIME to minimize memory usage
DATES=("2025-07-02" "2025-07-03" "2025-07-04" "2025-07-05" "2025-07-06" "2025-07-07")
SKIPPED_COUNT=0
PROCESSED_COUNT=0
MISSING_DATA=()

echo -e "${WHITE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${WHITE}           STAGE 1: SEGMENTATION & INCIDENT DETECTION          ${NC}"
echo -e "${WHITE}═══════════════════════════════════════════════════════════════${NC}"
echo

for date in "${DATES[@]}"; do
    echo -e "${CYAN}────────────────────────────────────────────────────────────────${NC}"
    echo -e "${CYAN}Date: ${date}${NC}"
    echo -e "${CYAN}────────────────────────────────────────────────────────────────${NC}"

    # Check if both segments AND incidents exist (fully processed)
    segment_file="data/segments/segments_${date}.parquet"
    incident_file="data/incidents/incidents_${date}.parquet"

    if [ -f "$segment_file" ] && [ -f "$incident_file" ]; then
        echo -e "${GREEN}✅ Day ${date} is fully processed${NC}"
        echo -e "   📁 Segments: $(du -h "$segment_file" 2>/dev/null | cut -f1)"
        echo -e "   🚨 Incidents: $(du -h "$incident_file" 2>/dev/null | cut -f1)"

        # Quick stats on existing incidents
        if command -v duckdb &> /dev/null; then
            incident_count=$(duckdb -noheader -list -c "SELECT COUNT(*) FROM '$incident_file'" 2>/dev/null || echo "N/A")
            echo -e "   📊 Incident count: $incident_count"
        fi

        SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
        echo
        continue
    fi

    # Check if raw data exists
    raw_file="data/raw/states_${date}.parquet"
    if [ ! -e "$raw_file" ]; then
        echo -e "${RED}✗ No raw data for ${date}${NC}"
        MISSING_DATA+=("$date")
        echo
        continue
    fi

    echo -e "${YELLOW}🔄 Processing required for ${date}${NC}"
    PROCESSED_COUNT=$((PROCESSED_COUNT + 1))

    # SEGMENTATION - only if doesn't exist
    if [ -f "$segment_file" ]; then
        echo -e "${GREEN}✓ Segments already exist${NC}"
    else
        echo -e "${YELLOW}⚙️  Segmenting flight paths...${NC}"
        echo -e "   Memory before: $(free -h | grep Mem | awk '{print $3 "/" $2}')"

        if uv run aviation-anomaly --config "$CONFIG_FILE" segment \
            --date "$date" \
            --output-dir data/segments; then
            echo -e "${GREEN}✓ Segmentation complete${NC}"
        else
            echo -e "${RED}✗ Segmentation failed${NC}"
            echo -e "${YELLOW}   Try: Reduce memory_limit to 8GB in config.toml${NC}"
            echo
            continue
        fi

        echo -e "   Memory after: $(free -h | grep Mem | awk '{print $3 "/" $2}')"
    fi

    # INCIDENT DETECTION - only if doesn't exist or is older than segments
    if [ -f "$incident_file" ] && [ "$incident_file" -nt "$segment_file" ]; then
        echo -e "${GREEN}✓ Incidents already detected${NC}"
    else
        echo -e "${YELLOW}🚨 Detecting incidents (production filter)...${NC}"

        if uv run aviation-anomaly --config "$CONFIG_FILE" detect \
            --date "$date" \
            --segments-dir data/segments \
            --output-dir data/incidents \
            --filter-profile production \
            --stats; then
            echo -e "${GREEN}✓ Detection complete${NC}"
        else
            echo -e "${RED}✗ Detection failed${NC}"
        fi
    fi

    echo -e "${BLUE}Memory status:${NC}"
    free -h | grep -E "Mem:|Swap:" | sed 's/^/  /'
    echo
done

# Summary of per-day processing
echo -e "${WHITE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${WHITE}                    STAGE 1 SUMMARY                            ${NC}"
echo -e "${WHITE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}📊 Processing Statistics:${NC}"
echo -e "   ✅ Days already complete: ${SKIPPED_COUNT}"
echo -e "   🔄 Days processed: ${PROCESSED_COUNT}"
if [ ${#MISSING_DATA[@]} -gt 0 ]; then
    echo -e "   ⚠️  Missing raw data for: ${MISSING_DATA[*]}"
fi
echo

# Count incidents per day
if ls data/incidents/incidents_2025-07-*.parquet 1> /dev/null 2>&1; then
    echo -e "${BLUE}📈 Incidents per day:${NC}"
    total_incidents=0
    for incident_file in data/incidents/incidents_2025-07-*.parquet; do
        if [ -f "$incident_file" ]; then
            date_part=$(basename "$incident_file" | sed 's/incidents_//;s/.parquet//')
            if command -v duckdb &> /dev/null; then
                count=$(duckdb -noheader -list -c "SELECT COUNT(*) FROM '$incident_file'" 2>/dev/null || echo "0")
                echo -e "   ${date_part}: $count incidents"
                total_incidents=$((total_incidents + count))
            fi
        fi
    done
    echo -e "   ${GREEN}Total: ${total_incidents} incidents${NC}"
    echo
fi

# Check if ALL days are processed before doing H3
ALL_PROCESSED=true
for date in "${DATES[@]}"; do
    segment_file="data/segments/segments_${date}.parquet"
    incident_file="data/incidents/incidents_${date}.parquet"
    if [ ! -f "$segment_file" ] || [ ! -f "$incident_file" ]; then
        ALL_PROCESSED=false
        break
    fi
done

if [ "$ALL_PROCESSED" = true ]; then
    echo -e "${WHITE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${WHITE}              STAGE 2: H3 AGGREGATION (ALL DAYS)               ${NC}"
    echo -e "${WHITE}═══════════════════════════════════════════════════════════════${NC}"
    echo

    echo -e "${CYAN}🗺️  All days processed - running H3 aggregation across full dataset${NC}"
    echo -e "${CYAN}   Using glob pattern to process all segment files at once${NC}"

    # H3 aggregation processes ALL data at once using glob pattern
    # Use --force flag if any new days were processed OR if segment files are newer than H3 files
    FORCE_FLAG=""
    H3_REF_FILE="data/h3/h3_coverage_r3.parquet"

    if [ "$PROCESSED_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}   Note: ${PROCESSED_COUNT} new day(s) processed - forcing H3 regeneration${NC}"
        FORCE_FLAG="--force"
    elif [ -f "$H3_REF_FILE" ]; then
        # Check if any segment files are newer than the H3 reference file
        NEWER_SEGMENTS=$(find data/segments -name 'segments_*.parquet' -newer "$H3_REF_FILE" 2>/dev/null | wc -l)
        if [ "$NEWER_SEGMENTS" -gt 0 ]; then
            echo -e "${YELLOW}   Note: Found $NEWER_SEGMENTS segment file(s) newer than H3 files - forcing regeneration${NC}"
            FORCE_FLAG="--force"
        fi
    else
        # H3 files don't exist yet
        echo -e "${YELLOW}   Note: H3 files don't exist yet - will generate${NC}"
    fi

    if uv run aviation-anomaly --config "$CONFIG_FILE" aggregate \
        --output-dir data/h3 \
        --resolutions 3,4,5,6,7 \
        $FORCE_FLAG; then
        echo -e "${GREEN}✓ H3 aggregation complete for all days${NC}"
        echo
    else
        echo -e "${RED}✗ H3 aggregation FAILED${NC}"
        echo -e "${RED}   Cannot continue to tile generation with failed aggregation${NC}"
        echo -e "${RED}   Check logs above for error details${NC}"
        exit 1
    fi

    # Tile generation only if H3 succeeded
    if ls data/h3/*.parquet 1> /dev/null 2>&1; then
        echo -e "${WHITE}═══════════════════════════════════════════════════════════════${NC}"
        echo -e "${WHITE}                 STAGE 3: TILE GENERATION                      ${NC}"
        echo -e "${WHITE}═══════════════════════════════════════════════════════════════${NC}"
        echo

        echo -e "${YELLOW}🌍 Generating tiles from H3 aggregations...${NC}"
        echo -e "${YELLOW}   Note: Generating GeoJSONL + PMTiles (web UI requires PMTiles)${NC}"

        if uv run aviation-anomaly --config "$CONFIG_FILE" tiles \
            --h3-dir data/h3 \
            --output-dir data/tiles \
            --pmtiles; then
            echo -e "${GREEN}✓ Tile generation complete (GeoJSONL + PMTiles)${NC}"
        else
            echo -e "${YELLOW}⚠️  Tile generation had issues${NC}"
            echo -e "${YELLOW}   If Tippecanoe is missing: https://github.com/mapbox/tippecanoe${NC}"
        fi
    fi
else
    echo -e "${YELLOW}⚠️  Cannot run H3 aggregation - not all days are processed${NC}"
    echo -e "${YELLOW}   Missing data prevents complete spatial aggregation${NC}"
    echo
    echo -e "   To complete processing, ensure all days have:"
    echo -e "   1. Segment files in data/segments/"
    echo -e "   2. Incident files in data/incidents/"
    echo
fi

echo
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}                    PIPELINE COMPLETE                          ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo

if [ "$ALL_PROCESSED" = true ]; then
    echo -e "${GREEN}✅ All stages complete!${NC}"
    echo -e "   You can now:"
    echo -e "   1. Start server: ${CYAN}uv run aviation-anomaly serve --port 8000${NC}"
    echo -e "   2. View at: ${CYAN}http://localhost:8000${NC}"
else
    echo -e "${YELLOW}⚠️  Pipeline partially complete${NC}"
    echo -e "   Some days are missing. Re-run this script after acquiring missing data."
fi

# ═══════════════════════════════════════════════════════════════
# POST-RUN DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "📄 Full log available at: ${PIPELINE_LOG_FILE}"

# Check for OOM errors in the log
if grep -q "oom\|killed\|out of memory" "${PIPELINE_LOG_FILE}" -i; then
    echo "⚠️  WARNING: Out of Memory errors detected in log!"
    echo "   Consider reducing memory usage by:"
    echo "   - Decreasing batch_size in config.toml"
    echo "   - Lowering duckdb.memory_limit in config.toml"
    echo "   - Processing fewer days at once"
fi

echo "═══════════════════════════════════════════════════════════════"
