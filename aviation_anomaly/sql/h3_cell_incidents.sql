-- Query incident details for a specific H3 cell
--
-- Parameters:
--   mapping_file: Path to incident-H3 mapping parquet file
--   incidents_file: Glob pattern for incidents parquet files (e.g., 'data/incidents/incidents_*.parquet')
--   h3_cell: H3 cell identifier (as integer)
--   emergency_type: Optional emergency type filter
--   limit: Maximum number of results
--   offset: Offset for pagination
--
-- Design: Incident start positions (start_lat, start_lon) are stored directly in the incidents table,
-- extracted once during detection. This avoids expensive segment joins and list_filter operations
-- at query time, improving drill-down performance from ~20s to <1s for typical queries.

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
    i.start_lat,
    i.start_lon
FROM '{{ incidents_file }}' i
JOIN cell_incidents ci ON i.incident_id = ci.incident_id
{% if emergency_type %}
WHERE i.emergency_type = '{{ emergency_type }}'
{% endif %}
ORDER BY i.start_time DESC
LIMIT {{ limit }}
OFFSET {{ offset }}
