-- 4.1 / 4.2 Evidence: settings, indexes, policies, compressed chunks, data checks, storage
\timing on

-- 4.1 Columnstore (compression) settings of both tables
SELECT * FROM timescaledb_information.hypertable_columnstore_settings
WHERE hypertable::text IN ('energy_time_compressed', 'energy_meter_compressed');

-- Chunk interval (same as the 1-day baseline)
SELECT hypertable_name, time_interval
FROM timescaledb_information.dimensions
WHERE hypertable_name IN ('energy_readings', 'energy_time_compressed', 'energy_meter_compressed');

-- Matching indexes
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE tablename IN ('energy_time_compressed', 'energy_meter_compressed')
ORDER BY tablename, indexname;

-- Policies: compress after 48 hours, currently paused (scheduled = f)
SELECT job_id, hypertable_name, proc_name, config, scheduled
FROM timescaledb_information.jobs
WHERE hypertable_name IN ('energy_time_compressed', 'energy_meter_compressed')
ORDER BY hypertable_name;

-- The same chunk time ranges are compressed in both tables
SELECT range_start, range_end,
       bool_or(is_compressed) FILTER (WHERE hypertable_name = 'energy_time_compressed')  AS time_compressed,
       bool_or(is_compressed) FILTER (WHERE hypertable_name = 'energy_meter_compressed') AS meter_compressed
FROM timescaledb_information.chunks
WHERE hypertable_name IN ('energy_time_compressed', 'energy_meter_compressed')
GROUP BY range_start, range_end
ORDER BY range_start;

SELECT hypertable_name,
       count(*) FILTER (WHERE is_compressed) AS compressed_chunks,
       count(*)                              AS total_chunks
FROM timescaledb_information.chunks
WHERE hypertable_name IN ('energy_time_compressed', 'energy_meter_compressed')
GROUP BY hypertable_name;

-- 4.1.6 Repeat the data checks from 3.1 (exact NUMERIC sums)
DROP TABLE IF EXISTS comp_checks;
CREATE TEMP TABLE comp_checks AS
SELECT 'energy_readings' AS tbl, count(*) AS row_count, count(DISTINCT meter_id) AS meters,
       min(event_time) AS earliest, max(event_time) AS latest,
       sum(power_kw::numeric) AS sum_power_kw, sum(energy_kwh::numeric) AS sum_energy_kwh
FROM energy_readings
UNION ALL
SELECT 'energy_time_compressed', count(*), count(DISTINCT meter_id), min(event_time),
       max(event_time), sum(power_kw::numeric), sum(energy_kwh::numeric)
FROM energy_time_compressed
UNION ALL
SELECT 'energy_meter_compressed', count(*), count(DISTINCT meter_id), min(event_time),
       max(event_time), sum(power_kw::numeric), sum(energy_kwh::numeric)
FROM energy_meter_compressed;

SELECT tbl, row_count, meters, earliest, latest FROM comp_checks ORDER BY tbl;

SELECT c.tbl, round(c.sum_power_kw, 6) AS sum_power_kw, round(c.sum_energy_kwh, 6) AS sum_energy_kwh,
       c.row_count = 10643735 AND c.meters = 4000        AS counts_ok,
       c.earliest = b.earliest AND c.latest = b.latest   AS dates_match,
       abs(c.sum_power_kw   - b.sum_power_kw)   <= 0.001 AS power_ok,
       abs(c.sum_energy_kwh - b.sum_energy_kwh) <= 0.001 AS energy_ok
FROM comp_checks c
CROSS JOIN (SELECT * FROM comp_checks WHERE tbl = 'energy_readings') b
ORDER BY c.tbl;

-- 4.2 Storage: all chunks (compressed and uncompressed) and their indexes
WITH sizes AS (
    SELECT t AS tbl, s.*
    FROM unnest(ARRAY['energy_readings', 'energy_time_compressed', 'energy_meter_compressed']) AS t,
         LATERAL hypertable_detailed_size(t::regclass) AS s
), base AS (
    SELECT total_bytes AS base_bytes FROM sizes WHERE tbl = 'energy_readings'
), logsum AS (
    SELECT table_name,
           count(*) FILTER (WHERE compressed)            AS compressed_chunks,
           count(*)                                       AS total_chunks,
           sum(rows_loaded) FILTER (WHERE compressed)     AS rows_in_compressed,
           sum(compress_s)                                AS compress_seconds
    FROM compression_log GROUP BY table_name
)
SELECT s.tbl,
       round((s.table_bytes + s.toast_bytes) / 1048576.0, 1)        AS data_mb,
       round(s.index_bytes / 1048576.0, 1)                          AS index_mb,
       round(s.total_bytes / 1048576.0, 1)                          AS total_mb,
       round(b.base_bytes::numeric / s.total_bytes, 2)              AS compression_ratio,
       round(100.0 * (b.base_bytes - s.total_bytes) / b.base_bytes, 1) AS pct_saved,
       coalesce(l.compressed_chunks, 0) || '/' ||
         (SELECT count(*) FROM timescaledb_information.chunks c
          WHERE c.hypertable_name = s.tbl)                          AS compressed_chunks,
       round(100.0 * coalesce(l.rows_in_compressed, 0) / 10643735, 2) AS pct_rows_compressed,
       round(coalesce(l.compress_seconds, 0)::numeric, 1)           AS compression_s
FROM sizes s
CROSS JOIN base b
LEFT JOIN logsum l ON l.table_name = s.tbl
ORDER BY s.total_bytes DESC;