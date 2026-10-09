-- 6.1 Three initially unpopulated continuous aggregates over energy_readings.
-- materialized_only = true: queries read stored buckets only (real-time aggregation off).

CREATE MATERIALIZED VIEW IF NOT EXISTS energy_15min_region
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT time_bucket(INTERVAL '15 minutes', r.event_time, 'Africa/Kigali') AS bucket,
       m.region,
       sum(r.energy_kwh) AS energy_kwh,
       sum(r.power_kw)   AS power_kw_sum,
       count(*)          AS reading_count
FROM energy_readings r
INNER JOIN meters m ON r.meter_id = m.meter_id
GROUP BY bucket, m.region
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS energy_hourly_region
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT time_bucket(INTERVAL '1 hour', r.event_time, 'Africa/Kigali') AS bucket,
       m.region,
       sum(r.energy_kwh) AS energy_kwh,
       sum(r.power_kw)   AS power_kw_sum,
       count(*)          AS reading_count
FROM energy_readings r
INNER JOIN meters m ON r.meter_id = m.meter_id
GROUP BY bucket, m.region
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS energy_daily_meter
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT time_bucket(INTERVAL '1 day', event_time, 'Africa/Kigali') AS bucket,
       meter_id,
       sum(energy_kwh) AS energy_kwh,
       sum(power_kw)   AS power_kw_sum,
       count(*)        AS reading_count
FROM energy_readings
GROUP BY bucket, meter_id
WITH NO DATA;

-- Confirm: created, real-time aggregation off, and still empty
SELECT view_name, materialized_only FROM timescaledb_information.continuous_aggregates ORDER BY view_name;
SELECT 'energy_15min_region' AS view, count(*) FROM energy_15min_region
UNION ALL SELECT 'energy_hourly_region', count(*) FROM energy_hourly_region
UNION ALL SELECT 'energy_daily_meter',   count(*) FROM energy_daily_meter;