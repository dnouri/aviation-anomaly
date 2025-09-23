-- H3 to GeoJSONL Export Pipeline
-- Outputs newline-delimited GeoJSON features (one per line)
-- Parameters:
--   {{coverage_table}}: Name of table/view with H3 coverage data
--   {{incidents_table}}: Name of table/view with H3 incident data (or 'NULL' if none)
--   {{has_incidents}}: Boolean flag indicating if incidents data exists
--   {{output_file}}: Path to write the GeoJSONL output file
-- Note: H3 and spatial extensions must be loaded on the connection
-- 
-- This query outputs individual GeoJSON features without aggregation,
-- avoiding memory issues with large datasets. Each row becomes a separate
-- JSON object suitable for streaming and line-by-line processing.

COPY (
    WITH combined AS (
        SELECT
            c.h3_cell,
            c.h3_res,
            c.unique_segments,
            c.unique_aircraft,
            c.total_points,
            {% if has_incidents %}
            i.incidents_unique,
            i.aircraft_with_incidents,
            i.incidents_coverage,
            i.unique_flights,
            i.total_segments,
            i.emergency_types_list,
            i.emergency_type_diversity,
            i.predominant_emergency_type,
            i.incident_rate
            {% else %}
            NULL as incidents_unique,
            NULL as aircraft_with_incidents,
            NULL as incidents_coverage,
            NULL as unique_flights,
            NULL as total_segments,
            NULL as emergency_types_list,
            NULL as emergency_type_diversity,
            NULL as predominant_emergency_type,
            NULL as incident_rate
            {% endif %}
        FROM {{ coverage_table }} c
        {% if has_incidents %}
        LEFT JOIN {{ incidents_table }} i ON c.h3_cell = i.h3_cell
        {% endif %}
    ),
    features AS (
        SELECT
            json_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(ST_GeomFromText(h3_cell_to_boundary_wkt(h3_cell)))::json,
                'properties', json_object(
                    'h3_cell', CAST(h3_cell AS VARCHAR),
                    'h3_res', h3_res,
                    'unique_segments', unique_segments,
                    'unique_aircraft', unique_aircraft,
                    'total_points', total_points,
                    'incidents_unique', incidents_unique,
                    'aircraft_with_incidents', aircraft_with_incidents,
                    'incidents_coverage', incidents_coverage,
                    'unique_flights', unique_flights,
                    'total_segments', total_segments,
                    'emergency_types_list', emergency_types_list,
                    'emergency_type_diversity', emergency_type_diversity,
                    'predominant_emergency_type', predominant_emergency_type,
                    'incident_rate', incident_rate
                )
            ) as feature
        FROM combined
    )
    -- Export each feature as a JSON string on its own line
    SELECT feature::VARCHAR as json_text
    FROM features
) TO '{{ output_file }}' 
(FORMAT CSV, HEADER FALSE, QUOTE '', ESCAPE '', DELIMITER E'\n', COMPRESSION 'gzip')