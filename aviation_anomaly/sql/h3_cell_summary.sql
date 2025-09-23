-- Query H3 cell summary statistics
-- Parameters:
--   h3_file: Path to H3 incidents parquet file  
--   h3_cell: H3 cell identifier (as integer)
--   emergency_type: Optional emergency type filter (7500/7600/7700)

SELECT 
    h3_cell,
    h3_res,
    incidents_unique,
    incidents_coverage,
    unique_flights,
    incident_rate,
    emergency_types_list,
    emergency_type_diversity,
    predominant_emergency_type
FROM '{{ h3_file }}'
WHERE h3_cell = {{ h3_cell }}
{% if emergency_type %}
    AND '{{ emergency_type }}' = ANY(emergency_types_list)
{% endif %}