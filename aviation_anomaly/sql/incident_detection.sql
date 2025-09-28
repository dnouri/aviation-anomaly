-- Incident Detection Pipeline with Quality Gates
-- Memory-safe processing of segments to detect emergency incidents
-- 
-- Quality Gates:
-- 1. Temporal: 5+ samples in 60 seconds
-- 2. Persistence: Emergency must last >45 seconds
-- 3. Airborne: <30% of samples on ground
-- 4. Roller-dial detection for confidence scoring

COPY (
    -- Load segments and extract emergency points (optimized single-pass)
    WITH emergency_segments AS (
        SELECT 
            segment_id,
            icao24,
            start_time,
            end_time,
            duration_seconds,
            point_count,
            -- Extract all emergency squawk points once
            list_filter(points, p -> p.squawk IN ('7500', '7600', '7700')) as emergency_points,
            -- Get roller-dial codes from the already filtered emergency-related codes
            list_distinct(list_transform(
                list_filter(points, p -> p.squawk LIKE '77%' AND p.squawk NOT IN ('7700', '7777')),
                p -> p.squawk
            )) as roller_dial_codes
        FROM '{{ input_path }}'
        -- Early filter: need at least 5 emergency points to possibly pass temporal gate
        WHERE list_count(list_filter(points, p -> p.squawk IN ('7500', '7600', '7700'))) >= 5
    ),
    
    -- Categorize emergency points by type (second pass on smaller array)
    categorized_segments AS (
        SELECT 
            segment_id,
            icao24,
            start_time,
            end_time,
            duration_seconds,
            point_count,
            emergency_points,
            -- Filter the already-extracted emergency points
            list_filter(emergency_points, p -> p.squawk = '7500') as hijack_points,
            list_filter(emergency_points, p -> p.squawk = '7600') as radio_failure_points,
            list_filter(emergency_points, p -> p.squawk = '7700') as general_emergency_points,
            roller_dial_codes
        FROM emergency_segments
    ),
    
    -- Apply temporal quality gate: 5+ samples in 60 seconds (optimized)
    temporal_checks AS (
        SELECT 
            segment_id,
            icao24,
            emergency_points,
            roller_dial_codes,
            -- Pre-compute temporal checks for each type
            (list_count(hijack_points) >= 5 
             AND hijack_points[5].time - hijack_points[1].time <= 60) as hijack_valid,
            (list_count(radio_failure_points) >= 5
             AND radio_failure_points[5].time - radio_failure_points[1].time <= 60) as radio_valid,
            (list_count(general_emergency_points) >= 5
             AND general_emergency_points[5].time - general_emergency_points[1].time <= 60) as general_valid,
            hijack_points,
            radio_failure_points,
            general_emergency_points
        FROM categorized_segments
    ),
    temporal_validation AS (
        SELECT
            segment_id,
            icao24,
            emergency_points,
            roller_dial_codes,
            -- Priority order: hijack > radio > general
            CASE 
                WHEN hijack_valid THEN '7500'
                WHEN radio_valid THEN '7600'
                WHEN general_valid THEN '7700'
                ELSE NULL
            END as emergency_type,
            CASE 
                WHEN hijack_valid THEN hijack_points
                WHEN radio_valid THEN radio_failure_points
                WHEN general_valid THEN general_emergency_points
                ELSE []
            END as validated_points
        FROM temporal_checks
    ),
    
    -- Apply persistence quality gate: >45 seconds
    persistence_validation AS (
        SELECT 
            segment_id,
            icao24,
            emergency_type,
            validated_points,
            roller_dial_codes,
            list_count(validated_points) as sample_count,
            validated_points[1].time as incident_start,
            validated_points[-1].time as incident_end,
            validated_points[-1].time - validated_points[1].time as persistence_seconds,
            CASE 
                WHEN validated_points[-1].time - validated_points[1].time > 45
                THEN true
                ELSE false
            END as passes_persistence
        FROM temporal_validation
        WHERE emergency_type IS NOT NULL
    ),
    
    -- Apply airborne quality gate: <30% on ground (optimized)
    airborne_validation AS (
        WITH ground_stats AS (
            SELECT 
                *,
                -- Compute ground count once
                list_count(list_filter(validated_points, p -> p.onground)) as ground_count
            FROM persistence_validation
            WHERE passes_persistence = true
        )
        SELECT 
            segment_id,
            icao24,
            emergency_type,
            sample_count,
            incident_start,
            incident_end,
            persistence_seconds,
            roller_dial_codes,
            ground_count,
            -- Use pre-computed ground_count
            ROUND(100.0 * ground_count / NULLIF(sample_count, 0), 2) as ground_percentage,
            -- Simple check using computed values
            (ground_count::FLOAT / NULLIF(sample_count, 0)) < 0.3 as passes_airborne
        FROM ground_stats
    ),
    
    -- Calculate confidence scores based on quality gates
    confidence_scoring AS (
        SELECT
            segment_id,
            icao24,
            emergency_type,
            sample_count,
            incident_start,
            incident_end,
            persistence_seconds,
            ground_percentage,
            roller_dial_codes,
            -- Base confidence from sample count (max 40 points)
            LEAST(sample_count * 2, 40) +
            -- Persistence bonus (max 30 points)
            CASE
                WHEN persistence_seconds > 180 THEN 30
                WHEN persistence_seconds > 120 THEN 20
                WHEN persistence_seconds > 60 THEN 10
                ELSE 5
            END +
            -- Airborne bonus (20 points)
            CASE WHEN ground_percentage < 10 THEN 20 ELSE 10 END +
            -- Roller-dial penalty
            CASE WHEN list_count(roller_dial_codes) > 0 THEN -10 ELSE 10 END
            as confidence_score,
            -- Determine confidence level
            CASE
                WHEN sample_count >= 10 AND persistence_seconds > 120 AND ground_percentage < 10
                THEN 'HIGH'
                WHEN sample_count >= 5 AND persistence_seconds > 60 AND ground_percentage < 20
                THEN 'MEDIUM'
                ELSE 'LOW'
            END as confidence_level
        FROM airborne_validation
        WHERE passes_airborne = true
    ),

    -- Apply filter profile parameters
    filtered_incidents AS (
        SELECT *
        FROM confidence_scoring
        WHERE
            -- Core confidence threshold
            confidence_score >= {{ min_confidence | default(50) }}

            -- Temporal coherence (Strategy 2)
            AND persistence_seconds >= {{ min_duration | default(45) }}

            -- Statistical outlier filtering (Strategy 1)
            AND (
                (emergency_type = '7500' AND sample_count <= {{ max_samples_7500 | default(99999) }})
                OR (emergency_type = '7600' AND sample_count <= {{ max_samples_7600 | default(99999) }})
                OR (emergency_type = '7700' AND sample_count <= {{ max_samples_7700 | default(99999) }})
            )

            -- Ensemble minimum samples (Strategy 3)
            AND (
                (emergency_type = '7500' AND sample_count >= {{ min_samples_7500 | default(5) }})
                OR (emergency_type = '7600' AND sample_count >= {{ min_samples_7600 | default(5) }})
                OR (emergency_type = '7700' AND sample_count >= {{ min_samples_7700 | default(5) }})
            )
    ),
    
    -- Create incident records
    incidents AS (
        SELECT
            -- Generate unique incident ID
            icao24 || '_' || CAST(incident_start AS VARCHAR) as incident_id,
            segment_id,
            icao24,
            emergency_type,
            incident_start as start_time,
            incident_end as end_time,
            persistence_seconds as duration_seconds,
            sample_count,
            ground_percentage,
            confidence_score,
            confidence_level,
            CASE WHEN list_count(roller_dial_codes) > 0 THEN true ELSE false END as has_roller_dial,
            roller_dial_codes,
            -- Add metadata
            CAST('{{ processing_date }}' AS DATE) as processing_date,
            CURRENT_TIMESTAMP as detected_at
        FROM filtered_incidents
    ),
    
    -- Apply debouncing: merge incidents within 15 minutes (optimized)
    with_groups AS (
        WITH gap_calc AS (
            SELECT *,
                   start_time - LAG(end_time) OVER (PARTITION BY icao24, emergency_type ORDER BY start_time) as gap_seconds
            FROM incidents
        )
        SELECT *,
               SUM(CASE WHEN gap_seconds IS NULL OR gap_seconds > 900 THEN 1 ELSE 0 END) 
                   OVER (PARTITION BY icao24, emergency_type ORDER BY start_time) as group_id
        FROM gap_calc
    ),
    debounced AS (
        SELECT 
            FIRST(incident_id) as incident_id,
            FIRST(segment_id) as segment_id,
            icao24,
            emergency_type,
            MIN(start_time) as start_time,
            MAX(end_time) as end_time,
            MAX(end_time) - MIN(start_time) as duration_seconds,
            SUM(sample_count) as total_samples,
            AVG(ground_percentage) as avg_ground_percentage,
            MAX(confidence_score) as max_confidence,
            FIRST(confidence_level) as confidence_level,
            BOOL_OR(has_roller_dial) as has_roller_dial,
            FIRST(roller_dial_codes) as roller_dial_codes,  -- Simplified
            FIRST(processing_date) as processing_date,
            FIRST(detected_at) as detected_at
        FROM with_groups
        GROUP BY icao24, emergency_type, group_id
    )
    
    -- Final output with duration cap
    SELECT 
        incident_id,
        segment_id,
        icao24,
        emergency_type,
        start_time,
        end_time,
        -- Cap duration at 90 minutes as per SPEC
        LEAST(duration_seconds, 5400) as duration_seconds,
        total_samples,
        ROUND(avg_ground_percentage, 2) as ground_percentage,
        max_confidence as confidence_score,
        confidence_level,
        has_roller_dial,
        roller_dial_codes,
        processing_date,
        detected_at
    FROM debounced
    ORDER BY start_time, icao24
    
) TO '{{ output_path }}' (FORMAT PARQUET, COMPRESSION 'zstd')