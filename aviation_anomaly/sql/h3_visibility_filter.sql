-- H3 Visibility Filter
-- Applies visibility thresholds to filter H3 cells based on minimum activity
-- Parameters:
--   {{aggregates_file}}: Path to H3 aggregates Parquet file
--   {{output_file}}: Path to filtered output file
--   {{min_flights}}: Minimum flight threshold for visibility
-- Note: DuckDB settings are configured on the connection

COPY (
    SELECT *
    FROM read_parquet('{{ aggregates_file }}')
    WHERE unique_segments >= {{ min_flights }}
    ORDER BY h3_cell
) TO '{{ output_file }}' (FORMAT PARQUET, COMPRESSION 'zstd')