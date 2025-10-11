-- H3 Coverage Metrics Pipeline
-- Computes coverage quality metrics including points-per-flight for H3 cells
-- Parameters:
--   {{segment_file}}: Path to segment Parquet file
--   {{output_file}}: Path to output metrics file
--   {{resolution}}: H3 resolution (3-6)
-- Note: DuckDB settings and H3 extension are configured on the connection

COPY (
    WITH segment_cells AS (
        -- Map segments to H3 cells with point distribution
        SELECT
            segment_id,
            icao24,
            point_count,
            list_distinct(
                list_transform(
                    points,
                    p -> h3_latlng_to_cell(p.lat, p.lon, {{ resolution }})
                )
            ) as h3_cells,
            len(list_distinct(
                list_transform(
                    points,
                    p -> h3_latlng_to_cell(p.lat, p.lon, {{ resolution }})
                )
            )) as num_cells
        FROM read_parquet('{{ segment_file }}')
        WHERE point_count >= 2
    ),
    
    cell_coverage AS (
        -- Expand to individual cell observations
        SELECT
            UNNEST(h3_cells) as h3_cell,
            segment_id,
            point_count,
            num_cells
        FROM segment_cells
    ),
    
    coverage_metrics AS (
        -- Calculate coverage quality metrics per cell
        SELECT
            h3_cell,
            COUNT(DISTINCT segment_id) as unique_segments,
            -- Points-per-flight metric for coverage quality assessment
            PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY CAST(point_count AS DOUBLE) / num_cells
            ) as median_points_per_cell,
            AVG(CAST(point_count AS DOUBLE) / num_cells) as avg_points_per_cell,
            -- Coverage category based on median points-per-flight
            CASE
                WHEN PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY CAST(point_count AS DOUBLE) / num_cells
                ) >= 10 THEN 'excellent'
                WHEN PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY CAST(point_count AS DOUBLE) / num_cells
                ) >= 6 THEN 'good'
                WHEN PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY CAST(point_count AS DOUBLE) / num_cells
                ) >= 3 THEN 'limited'
                ELSE 'poor'
            END as coverage_category
        FROM cell_coverage
        GROUP BY h3_cell
    )
    
    SELECT * FROM coverage_metrics
    ORDER BY h3_cell
    
) TO '{{ output_file }}' (FORMAT PARQUET, COMPRESSION 'zstd')