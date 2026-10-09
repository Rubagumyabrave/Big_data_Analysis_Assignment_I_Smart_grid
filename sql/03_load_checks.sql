-- 2.1.5 Checks after loading energy_readings (before cleaning)

-- Rows, meters and time range
SELECT count(*)                 AS total_rows,
       count(DISTINCT meter_id) AS distinct_meters,
       min(event_time)          AS earliest_event,
       max(event_time)          AS latest_event
FROM energy_readings;

-- How many chunks the hypertable has
SELECT count(*) AS chunk_count
FROM timescaledb_information.chunks
WHERE hypertable_name = 'energy_readings';

-- Size across all chunks: data, indexes, total
SELECT pg_size_pretty(table_bytes + toast_bytes)              AS table_data,
       pg_size_pretty(index_bytes)                            AS indexes,
       pg_size_pretty(total_bytes)                            AS total,
       round((table_bytes + toast_bytes) / 1024.0 / 1024, 1)  AS data_mb,
       round(index_bytes / 1024.0 / 1024, 1)                  AS index_mb,
       round(total_bytes / 1024.0 / 1024, 1)                  AS total_mb
FROM hypertable_detailed_size('energy_readings');