-- 4.3 Execution plans for both compressed tables (Q4: one meter, 22-28 Sep)
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(energy_kwh), avg(power_kw), max(power_kw)
FROM energy_time_compressed
WHERE meter_id = 1000000000
  AND event_time >= '2026-09-22 00:00:00+02' AND event_time < '2026-09-29 00:00:00+02';

EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(energy_kwh), avg(power_kw), max(power_kw)
FROM energy_meter_compressed
WHERE meter_id = 1000000000
  AND event_time >= '2026-09-22 00:00:00+02' AND event_time < '2026-09-29 00:00:00+02';