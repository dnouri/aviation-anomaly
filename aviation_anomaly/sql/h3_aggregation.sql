-- H3 Aggregation Pipeline
-- Computes H3 cell coverage from flight segments
-- Parameters:
--   {{segment_file}}: Path to segment Parquet file
--   {{output_file}}: Path to output aggregation Parquet file
--   {{resolution}}: H3 resolution (3-7)
--   {{memory_limit}}: DuckDB memory limit
--   {{threads}}: Number of threads
--   {{temp_directory}}: Temporary directory for spilling

-- Configure memory limits for safe execution
SET memory_limit = '{{ memory_limit }}';
SET threads = {{ threads }};
SET temp_directory = '{{ temp_directory }}';

-- Load H3 extension
INSTALL h3;
LOAD h3;

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
            COUNT(*) as total_points,
            LIST(DISTINCT segment_id ORDER BY segment_id) as segment_list,
            LIST(DISTINCT icao24 ORDER BY icao24) as aircraft_list
        FROM segment_cells
        GROUP BY h3_cell
    )
    
    SELECT 
        h3_cell,
        {{ resolution }} as h3_res,
        unique_segments,
        unique_aircraft,
        total_points,
        segment_list,
        aircraft_list
    FROM cell_aggregates
    ORDER BY h3_cell
    
) TO '{{ output_file }}' (FORMAT PARQUET, COMPRESSION 'zstd')