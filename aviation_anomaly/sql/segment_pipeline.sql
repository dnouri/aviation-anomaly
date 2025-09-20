-- Complete flight segmentation pipeline
-- Combines gap detection, distance calculation, and filtering in one query
-- Writes directly to Parquet file for streaming execution
-- Parameters:
--   {{input_path}}: Path to input Parquet file
--   {{output_path}}: Path to output Parquet file  
--   {{gap_threshold}}: Gap threshold in seconds (e.g., 1200 for 20 minutes)
--   {{min_duration}}: Minimum duration in seconds (e.g., 600)
--   {{min_distance}}: Minimum distance in km (e.g., 30)

-- Configure memory limits for safe execution
SET memory_limit = '{{ memory_limit }}';
SET threads = {{ threads }};
SET temp_directory = '{{ temp_directory }}';
SET max_temp_directory_size = '{{ max_temp_directory_size }}';

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
        ORDER BY icao24, time
    ),
    
    -- Step 2: Calculate time gaps and assign segment IDs
    gaps_detected AS (
        SELECT 
            *,
            time - LAG(time) OVER (PARTITION BY icao24 ORDER BY time) AS time_gap,
            -- New segment when gap exceeds threshold or first record
            CASE 
                WHEN time - LAG(time) OVER (PARTITION BY icao24 ORDER BY time) >= {{ gap_threshold }}
                    OR LAG(time) OVER (PARTITION BY icao24 ORDER BY time) IS NULL
                THEN 1 
                ELSE 0 
            END AS new_segment_flag
        FROM raw_data
    ),
    
    -- Step 3: Create cumulative segment IDs
    with_segment_ids AS (
        SELECT 
            *,
            SUM(new_segment_flag) OVER (PARTITION BY icao24 ORDER BY time) AS segment_num,
            -- Create unique segment ID
            icao24 || '_' || CAST(SUM(new_segment_flag) OVER (PARTITION BY icao24 ORDER BY time) AS VARCHAR) AS segment_id
        FROM gaps_detected
    ),
    
    -- Step 4: Aggregate points into segments
    segments_raw AS (
        SELECT 
            segment_id,
            icao24,
            MIN(time) AS start_time,
            MAX(time) AS end_time,
            MAX(time) - MIN(time) AS duration_seconds,
            COUNT(*) AS point_count,
            ARRAY_AGG({
                'time': time,
                'lat': lat,
                'lon': lon,
                'squawk': squawk,
                'onground': onground,
                'alert': alert
            }) AS points
        FROM with_segment_ids
        GROUP BY segment_id, icao24
    ),
    
    -- Step 5: Calculate distances using Haversine formula
    segments_with_distance AS (
        SELECT 
            segment_id,
            icao24,
            start_time,
            end_time,
            duration_seconds,
            point_count,
            points,
            -- Calculate total distance by summing distances between consecutive points
            (
                SELECT COALESCE(SUM(
                    2 * 6371 * ASIN(SQRT(
                        POWER(SIN(RADIANS(points[i+1].lat - points[i].lat) / 2), 2) +
                        COS(RADIANS(points[i].lat)) * COS(RADIANS(points[i+1].lat)) * 
                        POWER(SIN(RADIANS(points[i+1].lon - points[i].lon) / 2), 2)
                    ))
                ), 0)
                FROM GENERATE_SERIES(1, ARRAY_LENGTH(points) - 1) AS t(i)
            ) AS distance_km
        FROM segments_raw
    ),
    
    -- Step 6: Filter segments based on duration OR distance criteria
    filtered_segments AS (
        SELECT 
            segment_id,
            icao24,
            start_time,
            end_time,
            duration_seconds,
            distance_km,
            point_count,
            points,
            -- Track why segment was kept for debugging
            CASE 
                WHEN duration_seconds >= {{ min_duration }} 
                     AND distance_km >= {{ min_distance }} THEN 'both'
                WHEN duration_seconds >= {{ min_duration }} THEN 'duration'
                WHEN distance_km >= {{ min_distance }} THEN 'distance'
                ELSE 'filtered'
            END AS keep_reason
        FROM segments_with_distance
        WHERE 
            -- OR condition per requirements
            duration_seconds >= {{ min_duration }}
            OR distance_km >= {{ min_distance }}
    ),
    
    -- Step 7: Calculate squawk coverage for quality metrics
    final_segments AS (
        SELECT 
            segment_id,
            icao24,
            start_time,
            end_time,
            duration_seconds,
            distance_km,
            point_count,
            -- Calculate squawk coverage ratio using list operations
            list_count(list_filter(points, p -> p.squawk IS NOT NULL AND p.squawk != '')) AS squawk_count,
            CASE 
                WHEN point_count > 0 THEN 
                    CAST(list_count(list_filter(points, p -> p.squawk IS NOT NULL AND p.squawk != '')) AS DOUBLE) / CAST(point_count AS DOUBLE)
                ELSE 0.0
            END AS squawk_coverage_ratio,
            keep_reason,
            points
        FROM filtered_segments
    )
    
    -- Final output
    SELECT * 
    FROM final_segments
    ORDER BY icao24, start_time
) TO '{{ output_path }}' (FORMAT PARQUET, COMPRESSION 'zstd')