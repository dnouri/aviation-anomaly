-- H3 Incident Aggregation by Emergency Type
-- Aggregates incidents by squawk type (7500, 7600, 7700) for H3 cells
-- Parameters:
--   {{incidents_file}}: Path to incidents Parquet file
--   {{segments_file}}: Path to segments Parquet file
--   {{output_file}}: Path to output aggregation file
--   {{resolution}}: H3 resolution (3-7)
-- Note: DuckDB settings and H3 extension are configured on the connection

COPY (
    WITH incident_segments AS (
        -- Join incidents with segments to get point geometries
        SELECT
            i.incident_id,
            i.emergency_type,
            s.points
        FROM read_parquet('{{ incidents_file }}') i
        JOIN read_parquet('{{ segments_file }}') s
        ON i.segment_id = s.segment_id
    ),
    
    incident_cells AS (
        -- Convert incident points to H3 cells
        SELECT
            incident_id,
            emergency_type,
            h3_latlng_to_cell(p.lat, p.lon, {{ resolution }}) as h3_cell
        FROM (
            SELECT
                incident_id,
                emergency_type,
                UNNEST(points) as p
            FROM incident_segments
        ) i
        WHERE p.lat IS NOT NULL AND p.lon IS NOT NULL
    ),

    -- Count unique incidents by emergency type
    type_counts AS (
        SELECT
            h3_cell,
            COUNT(DISTINCT CASE WHEN emergency_type = '7500' THEN incident_id END) as incidents_7500,
            COUNT(DISTINCT CASE WHEN emergency_type = '7600' THEN incident_id END) as incidents_7600,
            COUNT(DISTINCT CASE WHEN emergency_type = '7700' THEN incident_id END) as incidents_7700,
            COUNT(DISTINCT incident_id) as incidents_all
        FROM incident_cells
        GROUP BY h3_cell
    )

    SELECT * FROM type_counts
    ORDER BY h3_cell
    
) TO '{{ output_file }}' (FORMAT PARQUET, COMPRESSION 'zstd')