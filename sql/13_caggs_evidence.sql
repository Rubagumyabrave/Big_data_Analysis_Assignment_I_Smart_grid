-- 6.1 Evidence: view settings and definitions, sample rows, policy settings, job status
SELECT view_name, materialized_only, materialization_hypertable_name
FROM timescaledb_information.continuous_aggregates ORDER BY view_name;

SELECT view_name, view_definition
FROM timescaledb_information.continuous_aggregates ORDER BY view_name;

SELECT * FROM energy_15min_region  ORDER BY bucket, region   LIMIT 5;
SELECT * FROM energy_hourly_region ORDER BY bucket, region   LIMIT 5;
SELECT * FROM energy_daily_meter   ORDER BY bucket, meter_id LIMIT 5;

SELECT 'energy_15min_region' AS view, count(*) AS rows, min(bucket), max(bucket) FROM energy_15min_region
UNION ALL SELECT 'energy_hourly_region', count(*), min(bucket), max(bucket) FROM energy_hourly_region
UNION ALL SELECT 'energy_daily_meter',   count(*), min(bucket), max(bucket) FROM energy_daily_meter;

SELECT job_id, hypertable_name AS view_name, schedule_interval, config, scheduled
FROM timescaledb_information.jobs
WHERE proc_name = 'policy_refresh_continuous_aggregate' ORDER BY job_id;

SELECT js.job_id, js.hypertable_name, js.job_status, js.last_run_status,
       js.last_run_started_at, js.next_start, js.total_runs, js.total_failures
FROM timescaledb_information.job_stats js
JOIN timescaledb_information.jobs j USING (job_id)
WHERE j.proc_name = 'policy_refresh_continuous_aggregate' ORDER BY js.job_id;