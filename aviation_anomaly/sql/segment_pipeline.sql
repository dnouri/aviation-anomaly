-- Optimized flight segmentation pipeline with volume-based batching
-- Processes a subset of aircraft to control memory usage, with batches balanced by data points
-- Parameters:
--   {{input_path}}: Path to input Parquet file
--   {{output_path}}: Path to output Parquet file  
--   {{batch_size}}: Target number of aircraft per batch (e.g., 100) - actual batches balanced by data volume
--   {{batch_number}}: Which batch to process (0-based)
--   {{gap_threshold}}: Gap threshold in seconds (e.g., 1200 for 20 minutes)
--   {{min_duration}}: Minimum duration in seconds (e.g., 600)
--   {{min_distance}}: Minimum distance in km (e.g., 30)
-- Note: DuckDB settings are configured on the connection, not in this query

COPY (
    -- Determine which aircraft belong to this batch using volume-based batching
    WITH aircraft_point_counts AS (
        SELECT 
            icao24,
            COUNT(*) as point_count
        FROM read_parquet('{{ input_path }}')
        WHERE lat IS NOT NULL AND lon IS NOT NULL
        GROUP BY icao24
    ),
    batch_parameters AS (
        SELECT 
            COUNT(*) as total_aircraft,
            SUM(point_count) as total_points,
            GREATEST(1, CAST(CEIL(CAST(COUNT(*) AS DOUBLE) / {{ batch_size }}) AS INTEGER)) as num_batches
        FROM aircraft_point_counts
    ),
    aircraft_with_cumulative AS (
        SELECT 
            a.icao24,
            a.point_count,
            SUM(a.point_count) OVER (ORDER BY a.icao24 ROWS UNBOUNDED PRECEDING) as cumulative_points,
            p.num_batches,
            CAST(p.total_points AS DOUBLE) / CAST(p.num_batches AS DOUBLE) as target_points_per_batch
        FROM aircraft_point_counts a
        CROSS JOIN batch_parameters p
    ),
    aircraft_batches AS (
        SELECT 
            icao24,
            LEAST(
                FLOOR((cumulative_points - 1) / target_points_per_batch),
                num_batches - 1
            ) as batch_id
        FROM aircraft_with_cumulative
    ),
    current_batch AS (
        SELECT icao24 
        FROM aircraft_batches
        WHERE batch_id = {{ batch_number }}
    ),
    raw_data AS (
        SELECT 
            r.icao24,
            r.time,
            r.lat,
            r.lon,
            r.squawk,
            r.onground,
            r.alert
        FROM read_parquet('{{ input_path }}') r
        WHERE r.icao24 IN (SELECT icao24 FROM current_batch)
          AND r.lat IS NOT NULL 
          AND r.lon IS NOT NULL
    ),
    
    -- Calculate gaps and segment IDs
    gaps_detected AS (
        SELECT 
            *,
            time - LAG(time) OVER (PARTITION BY icao24 ORDER BY time) AS time_gap,
            CASE 
                WHEN time - LAG(time) OVER (PARTITION BY icao24 ORDER BY time) >= {{ gap_threshold }}
                    OR LAG(time) OVER (PARTITION BY icao24 ORDER BY time) IS NULL
                THEN 1 
                ELSE 0 
            END AS new_segment_flag
        FROM raw_data
    ),
    
    -- Assign segment IDs and calculate point-to-point distances
    with_segment_metrics AS (
        SELECT 
            *,
            SUM(new_segment_flag) OVER (PARTITION BY icao24 ORDER BY time) AS segment_num,
            icao24 || '_' || CAST(SUM(new_segment_flag) OVER (PARTITION BY icao24 ORDER BY time) AS VARCHAR) AS segment_id,
            -- Calculate distance to previous point
            CASE 
                WHEN LAG(time) OVER (PARTITION BY icao24 ORDER BY time) IS NULL 
                    OR time - LAG(time) OVER (PARTITION BY icao24 ORDER BY time) >= {{ gap_threshold }}
                THEN 0  -- First point of segment
                ELSE 2 * 6371 * ASIN(SQRT(
                    POWER(SIN(RADIANS(lat - LAG(lat) OVER (PARTITION BY icao24 ORDER BY time)) / 2), 2) +
                    COS(RADIANS(LAG(lat) OVER (PARTITION BY icao24 ORDER BY time))) * COS(RADIANS(lat)) * 
                    POWER(SIN(RADIANS(lon - LAG(lon) OVER (PARTITION BY icao24 ORDER BY time)) / 2), 2)
                ))
            END AS distance_to_prev
        FROM gaps_detected
    ),
    
    -- Aggregate metrics before array creation for memory efficiency
    segment_metrics AS (
        SELECT 
            segment_id,
            icao24,
            MIN(time) AS start_time,
            MAX(time) AS end_time,
            MAX(time) - MIN(time) AS duration_seconds,
            COUNT(*) AS point_count,
            SUM(distance_to_prev) AS distance_km,
            COUNT(*) FILTER (WHERE squawk IS NOT NULL AND squawk != '') AS squawk_count
        FROM with_segment_metrics
        GROUP BY segment_id, icao24
    ),
    
    -- Determine which segments to keep based on metrics
    segments_to_keep AS (
        SELECT 
            segment_id,
            icao24,
            start_time,
            end_time,
            duration_seconds,
            distance_km,
            point_count,
            squawk_count,
            CAST(squawk_count AS DOUBLE) / CAST(point_count AS DOUBLE) AS squawk_coverage_ratio,
            CASE 
                WHEN duration_seconds >= {{ min_duration }} 
                     AND distance_km >= {{ min_distance }} THEN 'both'
                WHEN duration_seconds >= {{ min_duration }} THEN 'duration'
                WHEN distance_km >= {{ min_distance }} THEN 'distance'
                ELSE 'filtered'
            END AS keep_reason
        FROM segment_metrics
        WHERE duration_seconds >= {{ min_duration }}
           OR distance_km >= {{ min_distance }}
    ),
    
    -- Aggregate points for kept segments
    final_segments AS (
        SELECT 
            k.segment_id,
            k.icao24,
            k.start_time,
            k.end_time,
            k.duration_seconds,
            k.distance_km,
            k.point_count,
            k.squawk_count,
            k.squawk_coverage_ratio,
            k.keep_reason,
            ARRAY_AGG({
                'time': p.time,
                'lat': p.lat,
                'lon': p.lon,
                'squawk': p.squawk,
                'onground': p.onground,
                'alert': p.alert
            } ORDER BY p.time) AS points
        FROM segments_to_keep k
        JOIN with_segment_metrics p ON k.segment_id = p.segment_id
        GROUP BY 
            k.segment_id,
            k.icao24,
            k.start_time,
            k.end_time,
            k.duration_seconds,
            k.distance_km,
            k.point_count,
            k.squawk_count,
            k.squawk_coverage_ratio,
            k.keep_reason
    )
    
    -- Final output
    SELECT * 
    FROM final_segments
) TO '{{ output_path }}' (FORMAT PARQUET, COMPRESSION 'zstd')