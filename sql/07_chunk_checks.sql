-- 3.1 Verify the three chunk configurations
\timing on

-- Chunk interval of each hypertable
SELECT hypertable_name, column_name, time_interval
FROM timescaledb_information.dimensions
WHERE hypertable_name IN ('energy_readings_3h', 'energy_readings', 'energy_readings_week')
ORDER BY time_interval;

-- Chunk count and the time span the chunks cover
SELECT hypertable_name,
       count(*)         AS chunk_count,
       min(range_start) AS first_chunk_start,
       max(range_end)   AS last_chunk_end
FROM timescaledb_information.chunks
WHERE hypertable_name IN ('energy_readings_3h', 'energy_readings', 'energy_readings_week')
GROUP BY hypertable_name
ORDER BY chunk_count DESC;

-- Indexes: method and column order must match across the three tables
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE tablename IN ('energy_readings_3h', 'energy_readings', 'energy_readings_week')
ORDER BY tablename, indexname;

-- Data checks (sums in exact NUMERIC, so they compare without floating-point noise)
DROP TABLE IF EXISTS chunk_checks;
CREATE TEMP TABLE chunk_checks AS
SELECT 'energy_readings_3h' AS tbl, count(*) AS row_count,
       count(DISTINCT meter_id) AS meters, min(event_time) AS earliest,
       max(event_time) AS latest, sum(power_kw::numeric) AS sum_power_kw,
       sum(energy_kwh::numeric) AS sum_energy_kwh
FROM energy_readings_3h
UNION ALL
SELECT 'energy_readings', count(*), count(DISTINCT meter_id), min(event_time),
       max(event_time), sum(power_kw::numeric), sum(energy_kwh::numeric)
FROM energy_readings
UNION ALL
SELECT 'energy_readings_week', count(*), count(DISTINCT meter_id), min(event_time),
       max(event_time), sum(power_kw::numeric), sum(energy_kwh::numeric)
FROM energy_readings_week;

SELECT tbl, row_count, meters, earliest, latest
FROM chunk_checks ORDER BY tbl;

SELECT c.tbl,
       round(c.sum_power_kw, 6)                          AS sum_power_kw,
       round(c.sum_energy_kwh, 6)                        AS sum_energy_kwh,
       c.row_count = 10643735 AND c.meters = 4000        AS counts_ok,
       c.earliest = b.earliest AND c.latest = b.latest   AS dates_match,
       abs(c.sum_power_kw   - b.sum_power_kw)   <= 0.001 AS power_within_0_001,
       abs(c.sum_energy_kwh - b.sum_energy_kwh) <= 0.001 AS energy_within_0_001
FROM chunk_checks c
CROSS JOIN (SELECT * FROM chunk_checks WHERE tbl = 'energy_readings') b
ORDER BY c.tbl;