-- 2.2 Data quality of energy_readings BEFORE cleaning
-- A unique reading = one (meter_id, event_time) pair.
\timing on

-- 1. One row per observed pair: how many copies, and when it arrived
DROP TABLE IF EXISTS dq_pairs;
CREATE TEMP TABLE dq_pairs AS
SELECT meter_id, event_time,
       count(*)           AS copies,
       min(received_time) AS received_time   -- duplicate copies are identical
FROM energy_readings
GROUP BY meter_id, event_time;

-- 2. The planned grid: every registered meter x every 15-minute slot (28 days)
DROP TABLE IF EXISTS dq_grid;
CREATE TEMP TABLE dq_grid AS
SELECT m.meter_id, s AS event_time
FROM meters m
CROSS JOIN generate_series(timestamptz '2026-09-01 00:00+02',
                           timestamptz '2026-09-28 23:45+02',
                           interval '15 minutes') AS s;

-- 3. Missing pairs: in the grid but never observed (anti-join)
DROP TABLE IF EXISTS dq_missing;
CREATE TEMP TABLE dq_missing AS
SELECT g.meter_id, g.event_time
FROM dq_grid g
LEFT JOIN dq_pairs p USING (meter_id, event_time)
WHERE p.meter_id IS NULL;

-- 4. Summary counts, percentages and consistency checks
DROP TABLE IF EXISTS dq_summary;
CREATE TEMP TABLE dq_summary AS
SELECT (SELECT count(*) FROM dq_grid)                       AS planned,
       (SELECT count(*) FROM energy_readings)               AS emitted,
       (SELECT count(*) FROM dq_pairs)                      AS uniq,
       (SELECT sum(copies - 1) FROM dq_pairs)::bigint       AS extra_copies,
       (SELECT count(*) FROM dq_pairs
         WHERE received_time > event_time + interval '15 minutes') AS delayed,
       (SELECT count(*) FROM dq_missing)                    AS missing;

\x on
SELECT planned, emitted, uniq AS unique_pairs, extra_copies, delayed, missing,
       round(100.0 * missing      / planned, 4) AS missing_pct,
       round(100.0 * extra_copies / uniq,    4) AS duplicate_pct,
       round(100.0 * delayed      / uniq,    4) AS delayed_pct,
       round(100.0 * uniq         / planned, 4) AS completeness_pct,
       uniq + extra_copies = emitted            AS check_unique_plus_extra_eq_emitted,
       planned - uniq = missing                 AS check_planned_minus_unique_eq_missing
FROM dq_summary;
\x off

-- 5. Compare with the reference table in the brief
SELECT metric, measured, expected, measured = expected AS matches
FROM dq_summary,
LATERAL (VALUES
    ('planned_readings',        planned,      10752000::bigint),
    ('emitted_readings',        emitted,      10696848::bigint),
    ('unique_readings',         uniq,         10643735::bigint),
    ('duplicate_readings',      extra_copies,    53113::bigint),
    ('delayed_unique_readings', delayed,        213090::bigint),
    ('missing_readings',        missing,        108265::bigint)
) AS ref(metric, measured, expected);

-- 6. Arrival delays: normal = exactly 15 min, delayed should be 30-180 min
SELECT CASE WHEN received_time - event_time = interval '15 minutes' THEN 'on time (15 min)'
            WHEN received_time - event_time BETWEEN interval '30 minutes'
                                                AND interval '180 minutes' THEN 'delayed (30-180 min)'
            ELSE 'other' END                 AS arrival_class,
       count(*)                              AS unique_pairs,
       min(received_time - event_time)       AS min_delay,
       max(received_time - event_time)       AS max_delay
FROM dq_pairs
GROUP BY 1
ORDER BY 1;

-- 7. Five meters with the most missing readings (RANK shows ties honestly)
SELECT *
FROM (SELECT d.meter_id, m.region, m.customer_type,
             count(*)                            AS missing_readings,
             RANK() OVER (ORDER BY count(*) DESC) AS rnk
      FROM dq_missing d
      JOIN meters m USING (meter_id)
      GROUP BY d.meter_id, m.region, m.customer_type) t
WHERE rnk <= 5
ORDER BY missing_readings DESC, meter_id;