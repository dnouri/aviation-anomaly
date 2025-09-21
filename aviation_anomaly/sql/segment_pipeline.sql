-- Optimized flight segmentation pipeline with reduced memory usage
-- Calculates metrics before aggregating arrays to minimize memory pressure
-- Parameters:
--   {{input_path}}: Path to input Parquet file
--   {{output_path}}: Path to output Parquet file  
--   {{gap_threshold}}: Gap threshold in seconds (e.g., 1200 for 20 minutes)
--   {{min_duration}}: Minimum duration in seconds (e.g., 600)
--   {{min_distance}}: Minimum distance in km (e.g., 30)
-- Note: DuckDB settings are configured on the connection

COPY (
    WITH raw_data AS (
        SELECT 
            icao24,
            time,
            lat,
            lon,
            squawk,
            onground,
            alert
        FROM read_parquet('{{ input_path }}')
        WHERE lat IS NOT NULL 
          AND lon IS NOT NULL
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
    
    -- Aggregate metrics WITHOUT creating arrays yet
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
    
    -- Now aggregate points ONLY for segments we're keeping
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
    ORDER BY icao24, start_time
) TO '{{ output_path }}' (FORMAT PARQUET, COMPRESSION 'zstd')