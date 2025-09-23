-- Query incident details for a specific H3 cell
-- Parameters:
--   mapping_file: Path to incident-H3 mapping parquet file
--   incidents_file: Path to incidents parquet file  
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
    i.duration_seconds
FROM '{{ incidents_file }}' i
JOIN cell_incidents ci ON i.incident_id = ci.incident_id
{% if emergency_type %}
WHERE i.emergency_type = '{{ emergency_type }}'
{% endif %}
ORDER BY i.start_time DESC
LIMIT {{ limit }}
OFFSET {{ offset }}