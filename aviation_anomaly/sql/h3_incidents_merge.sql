-- H3 Incidents Merge Pipeline
-- Merges per-day H3 incident metrics into final aggregate
-- Parameters:
--   {{daily_pattern}}: Glob pattern for daily files (e.g., 'daily/h3_incidents_r5_*.parquet')
--   {{output_file}}: Path to merged output file
--   {{resolution}}: H3 resolution (for validation)
--
-- Behavior:
--   - Groups by h3_cell and sums counts across all days
--   - Merges emergency_types_list arrays (keeps all unique types)
--   - Recalculates derived metrics (diversity, predominant type, rates)
--   - Handles cells that appear in multiple days (esp. high-traffic areas)

COPY (
    WITH merged_counts AS (
        SELECT
            h3_cell,
            h3_res,
            SUM(incidents_unique) as incidents_unique,
            SUM(aircraft_with_incidents) as aircraft_with_incidents,
            SUM(incidents_coverage) as incidents_coverage,
            SUM(unique_segments) as unique_segments,
            SUM(total_segments) as total_segments,
            -- Collect all emergency type lists for post-processing
            LIST(emergency_types_list) as all_type_lists
        FROM read_parquet('{{ daily_pattern }}')
        WHERE h3_res = {{ resolution }}
        GROUP BY h3_cell, h3_res
    ),

    with_type_metrics AS (
        SELECT
            *,
            -- Flatten all type lists into single unique list
            LIST_SORT(LIST_DISTINCT(FLATTEN(all_type_lists))) as emergency_types_list,
            -- Count unique types
            LEN(LIST_DISTINCT(FLATTEN(all_type_lists))) as emergency_type_diversity
        FROM merged_counts
    ),

    with_mode AS (
        SELECT
            mc.*,
            -- Get predominant type by unnesting and finding mode
            (
                SELECT MODE(type)
                FROM (SELECT UNNEST(FLATTEN(mc.all_type_lists)) as type)
            ) as predominant_emergency_type
        FROM with_type_metrics mc
    )

    SELECT
        h3_cell,
        h3_res,
        incidents_unique,
        aircraft_with_incidents,
        incidents_coverage,
        unique_segments,
        total_segments,
        emergency_types_list,
        emergency_type_diversity,
        predominant_emergency_type,
        -- Recalculate incident rate from summed values
        CASE
            WHEN unique_segments > 0
            THEN CAST(incidents_unique AS FLOAT) / unique_segments
            ELSE NULL
        END as incident_rate
    FROM with_mode
    ORDER BY h3_cell
) TO '{{ output_file }}' (FORMAT PARQUET, COMPRESSION 'zstd')
