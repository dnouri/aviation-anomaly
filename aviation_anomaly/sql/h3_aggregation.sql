-- H3 Aggregation Pipeline
-- Computes H3 cell coverage from flight segments
-- Parameters:
--   {{segment_file}}: Path to segment Parquet file
--   {{output_file}}: Path to output aggregation Parquet file
--   {{resolution}}: H3 resolution (3-6)
-- Note: DuckDB settings and H3 extension are configured on the connection

COPY (
    WITH segment_cells AS (
        -- Extract all points and convert to H3 cells
        SELECT 
            s.segment_id,
            s.icao24,
            h3_latlng_to_cell(p.lat, p.lon, {{ resolution }}) as h3_cell
        FROM (
            SELECT 
                segment_id,
                icao24,
                UNNEST(points) as p
            FROM read_parquet('{{ segment_file }}')
            WHERE point_count >= 2
        ) s
        WHERE p.lat IS NOT NULL AND p.lon IS NOT NULL
    ),
    
    -- Aggregate by H3 cell
    cell_aggregates AS (
        SELECT
            h3_cell,
            COUNT(DISTINCT segment_id) as unique_segments,
            COUNT(DISTINCT icao24) as unique_aircraft,
            COUNT(*) as total_points
        FROM segment_cells
        GROUP BY h3_cell
    )

    SELECT
        h3_cell,
        {{ resolution }} as h3_res,
        unique_segments,
        unique_aircraft,
        total_points
    FROM cell_aggregates
    
) TO '{{ output_file }}' (FORMAT PARQUET, COMPRESSION 'zstd')