-- Incident to H3 Cell Mapping
-- Creates a lookup table for efficient drill-down queries
-- Parameters:
--   {{incidents_file}}: Path to incidents Parquet file
--   {{segments_file}}: Path to segments Parquet file
--   {{output_file}}: Path to output mapping Parquet file
--   {{resolution}}: H3 resolution (3-6)

COPY (
    -- Join incidents with segments to get trajectory points
    WITH incident_segments AS (
        SELECT
            i.incident_id,
            i.segment_id,
            i.icao24,
            i.emergency_type,
            s.points
        FROM read_parquet('{{ incidents_file }}') i
        JOIN read_parquet('{{ segments_file }}') s
        ON i.segment_id = s.segment_id
    ),
    
    -- Extract points and compute H3 cells for each incident
    incident_cells AS (
        SELECT DISTINCT
            incident_id,
            h3_latlng_to_cell(p.lat, p.lon, {{ resolution }}) as h3_cell,
            {{ resolution }} as h3_res
        FROM (
            SELECT
                incident_id,
                UNNEST(points) as p
            FROM incident_segments
        ) i
        WHERE p.lat IS NOT NULL AND p.lon IS NOT NULL
    )
    
    -- Output the mapping
    SELECT 
        incident_id,
        h3_cell,
        h3_res
    FROM incident_cells
    ORDER BY incident_id, h3_cell
) TO '{{ output_file }}' (FORMAT PARQUET, COMPRESSION 'zstd')