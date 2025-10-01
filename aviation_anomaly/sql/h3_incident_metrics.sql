-- H3 Incident Metrics Aggregation
-- Computes dual incident metrics by joining incidents with segments
-- Parameters:
--   {{incidents_file}}: Path to incidents Parquet file
--   {{segments_file}}: Path to segments Parquet file
--   {{output_file}}: Path to output aggregation Parquet file
--   {{resolution}}: H3 resolution (3-7)

COPY (
    -- First, join incidents with segments to get points
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
    
    -- Then get H3 cells for incidents
    incident_cells AS (
        SELECT
            incident_id,
            icao24,
            emergency_type,
            h3_latlng_to_cell(p.lat, p.lon, {{ resolution }}) as h3_cell
        FROM (
            SELECT
                incident_id,
                icao24,
                emergency_type,
                UNNEST(points) as p
            FROM incident_segments
        ) i
        WHERE p.lat IS NOT NULL AND p.lon IS NOT NULL
    ),

    -- Count unique incidents per cell and aggregate emergency types
    incident_unique_counts AS (
        SELECT
            h3_cell,
            COUNT(DISTINCT incident_id) as incidents_unique,
            COUNT(DISTINCT icao24) as aircraft_with_incidents,
            -- Emergency type aggregation
            LIST_SORT(LIST_DISTINCT(LIST(emergency_type))) as emergency_types_list,
            COUNT(DISTINCT emergency_type) as emergency_type_diversity,
            MODE(emergency_type) as predominant_emergency_type,
            -- Type-specific counters enable filtering to cells containing each type
            COUNT(DISTINCT CASE WHEN emergency_type = '7500' THEN incident_id END) as incidents_7500,
            COUNT(DISTINCT CASE WHEN emergency_type = '7600' THEN incident_id END) as incidents_7600,
            COUNT(DISTINCT CASE WHEN emergency_type = '7700' THEN incident_id END) as incidents_7700
        FROM incident_cells
        GROUP BY h3_cell
    ),

    -- Count all incident observations per cell (for heatmap)
    incident_coverage_counts AS (
        SELECT
            h3_cell,
            COUNT(*) as incidents_coverage
        FROM incident_cells
        GROUP BY h3_cell
    ),

    -- Get flight counts from segments
    flight_counts AS (
        SELECT
            h3_latlng_to_cell(p.lat, p.lon, {{ resolution }}) as h3_cell,
            COUNT(DISTINCT s.segment_id) as unique_segments,
            COUNT(DISTINCT s.segment_id) as total_segments
        FROM (
            SELECT segment_id, icao24, UNNEST(points) as p
            FROM read_parquet('{{ segments_file }}')
        ) s
        WHERE p.lat IS NOT NULL AND p.lon IS NOT NULL
        GROUP BY h3_cell
    ),

    -- Combine all metrics
    combined AS (
        SELECT
            COALESCE(iu.h3_cell, ic.h3_cell, f.h3_cell) as h3_cell,
            {{ resolution }} as h3_res,
            COALESCE(iu.incidents_unique, 0) as incidents_unique,
            COALESCE(iu.aircraft_with_incidents, 0) as aircraft_with_incidents,
            COALESCE(ic.incidents_coverage, 0) as incidents_coverage,
            COALESCE(f.unique_segments, 0) as unique_segments,
            COALESCE(f.total_segments, 0) as total_segments,
            -- Emergency type fields
            iu.emergency_types_list,
            COALESCE(iu.emergency_type_diversity, 0) as emergency_type_diversity,
            iu.predominant_emergency_type,
            -- Type-specific counters
            COALESCE(iu.incidents_7500, 0) as incidents_7500,
            COALESCE(iu.incidents_7600, 0) as incidents_7600,
            COALESCE(iu.incidents_7700, 0) as incidents_7700,
            -- Calculate rates
            CASE
                WHEN COALESCE(f.unique_segments, 0) > 0
                THEN CAST(COALESCE(iu.incidents_unique, 0) AS FLOAT) / f.unique_segments
                ELSE NULL
            END as incident_rate
        FROM incident_unique_counts iu
        FULL OUTER JOIN incident_coverage_counts ic ON iu.h3_cell = ic.h3_cell
        FULL OUTER JOIN flight_counts f ON COALESCE(iu.h3_cell, ic.h3_cell) = f.h3_cell
    )

    SELECT * FROM combined
    ORDER BY h3_cell
) TO '{{ output_file }}' (FORMAT PARQUET, COMPRESSION 'zstd')