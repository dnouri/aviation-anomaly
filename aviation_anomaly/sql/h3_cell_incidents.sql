-- Query incident details for a specific H3 cell with position data
-- Parameters:
--   mapping_file: Path to incident-H3 mapping parquet file
--   incidents_file: Path to incidents parquet file
--   segments_file: Path to segments parquet file (for position data)
--   h3_cell: H3 cell identifier (as integer)
--   emergency_type: Optional emergency type filter
--   limit: Maximum number of results
--   offset: Offset for pagination

WITH cell_incidents AS (
    SELECT DISTINCT incident_id
    FROM '{{ mapping_file }}'
    WHERE h3_cell = {{ h3_cell }}
)
SELECT
    i.incident_id,
    i.start_time,
    i.end_time,
    i.emergency_type,
    i.icao24,
    i.confidence_score,
    i.duration_seconds,
    s.points[1].lat as start_lat,
    s.points[1].lon as start_lon
FROM '{{ incidents_file }}' i
JOIN cell_incidents ci ON i.incident_id = ci.incident_id
JOIN '{{ segments_file }}' s ON i.segment_id = s.segment_id
{% if emergency_type %}
WHERE i.emergency_type = '{{ emergency_type }}'
{% endif %}
ORDER BY i.start_time DESC
LIMIT {{ limit }}
OFFSET {{ offset }}