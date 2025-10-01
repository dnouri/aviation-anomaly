-- H3 Coverage Merge Pipeline
-- Merges per-day H3 coverage files into final aggregate
-- Parameters:
--   {{daily_pattern}}: Glob pattern for daily files (e.g., 'daily/h3_coverage_r5_*.parquet')
--   {{output_file}}: Path to merged output file
--   {{resolution}}: H3 resolution (for validation)
--
-- Behavior:
--   - Groups by h3_cell and sums counts across all days
--   - Drops segment_list and aircraft_list (too large for merged output)
--   - Lightweight: merges ~1.1M aggregated records vs 1.19B raw points

COPY (
    SELECT
        h3_cell,
        h3_res,
        SUM(unique_segments) as unique_segments,
        SUM(unique_aircraft) as unique_aircraft,
        SUM(total_points) as total_points
    FROM read_parquet('{{ daily_pattern }}')
    WHERE h3_res = {{ resolution }}
    GROUP BY h3_cell, h3_res
    ORDER BY h3_cell
) TO '{{ output_file }}' (FORMAT PARQUET, COMPRESSION 'zstd')
