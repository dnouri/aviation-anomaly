-- Incident H3 Mapping Merge Pipeline
-- Merges per-day incident-to-H3 mapping files into final lookup table
-- Parameters:
--   {{daily_pattern}}: Glob pattern for daily files (e.g., 'daily/incident_h3_mapping_r5_*.parquet')
--   {{output_file}}: Path to merged output file
--   {{resolution}}: H3 resolution (for validation)
--
-- Behavior:
--   - Deduplicates (incident_id, h3_cell) pairs across all days
--   - Handles incidents that span midnight (same incident in multiple days)
--   - Produces clean lookup table for drill-down API queries

COPY (
    SELECT DISTINCT
        incident_id,
        h3_cell,
        h3_res
    FROM read_parquet('{{ daily_pattern }}')
    WHERE h3_res = {{ resolution }}
    ORDER BY incident_id, h3_cell
) TO '{{ output_file }}' (FORMAT PARQUET, COMPRESSION 'zstd')
