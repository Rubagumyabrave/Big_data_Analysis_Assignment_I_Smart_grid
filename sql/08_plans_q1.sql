-- 3.2 One execution plan per chunk configuration (Q1), with actual timing and buffers
EXPLAIN (ANALYZE, BUFFERS)
SELECT date_trunc('hour', event_time, 'Africa/Kigali') AS hour_cat, avg(power_kw), count(*)
FROM energy_readings_3h
WHERE event_time >= '2026-09-21 00:00:00+02' AND event_time < '2026-09-22 00:00:00+02'
GROUP BY 1 ORDER BY 1;

EXPLAIN (ANALYZE, BUFFERS)
SELECT date_trunc('hour', event_time, 'Africa/Kigali') AS hour_cat, avg(power_kw), count(*)
FROM energy_readings
WHERE event_time >= '2026-09-21 00:00:00+02' AND event_time < '2026-09-22 00:00:00+02'
GROUP BY 1 ORDER BY 1;

EXPLAIN (ANALYZE, BUFFERS)
SELECT date_trunc('hour', event_time, 'Africa/Kigali') AS hour_cat, avg(power_kw), count(*)
FROM energy_readings_week
WHERE event_time >= '2026-09-21 00:00:00+02' AND event_time < '2026-09-22 00:00:00+02'
GROUP BY 1 ORDER BY 1;