-- 4.3.3 Resume the compression policies after the query measurements
SELECT alter_job(job_id, scheduled => true)
FROM timescaledb_information.jobs
WHERE hypertable_name IN ('energy_time_compressed', 'energy_meter_compressed')
  AND proc_name = 'policy_compression';

SELECT job_id, hypertable_name, proc_name, config, scheduled, next_start
FROM timescaledb_information.jobs
WHERE hypertable_name IN ('energy_time_compressed', 'energy_meter_compressed')
ORDER BY hypertable_name;