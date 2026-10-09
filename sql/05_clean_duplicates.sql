-- 2.3 Remove exact duplicate readings from energy_readings.
-- Repeatable: a second run finds no duplicate groups and deletes nothing.
-- Missing readings are left as gaps (never filled with zero).
\timing on

-- 1. BEFORE cleaning
DROP TABLE IF EXISTS clean_before;
CREATE TEMP TABLE clean_before AS
SELECT count(*) AS row_count, sum(energy_kwh) AS total_energy_kwh
FROM energy_readings;

SELECT 'before cleaning' AS stage, row_count,
       round(total_energy_kwh::numeric, 6) AS total_energy_kwh
FROM clean_before;

-- 2. INVESTIGATE: every pair that occurs more than once
DROP TABLE IF EXISTS dup_groups;
CREATE TEMP TABLE dup_groups AS
SELECT meter_id, event_time,
       count(*) AS copies,
       count(DISTINCT (received_time, power_kw, voltage_v,
                       current_a, frequency_hz, energy_kwh)) AS distinct_versions,
       sum(energy_kwh) - min(energy_kwh) AS extra_energy_kwh
FROM energy_readings
GROUP BY meter_id, event_time
HAVING count(*) > 1;

SELECT count(*)                                      AS duplicate_groups,
       sum(copies - 1)                               AS extra_copies,
       max(copies)                                   AS max_copies_per_pair,
       count(*) FILTER (WHERE distinct_versions = 1) AS identical_groups,
       count(*) FILTER (WHERE distinct_versions > 1) AS conflicting_groups
FROM dup_groups;

-- Example: two duplicate groups shown in full
SELECT e.*
FROM energy_readings e
JOIN (SELECT meter_id, event_time FROM dup_groups
      ORDER BY meter_id, event_time LIMIT 2) g USING (meter_id, event_time)
ORDER BY e.meter_id, e.event_time;

-- Conflicting groups (same pair, different values). Must be empty before deleting.
SELECT * FROM dup_groups WHERE distinct_versions > 1 LIMIT 10;

-- 3. DELETE extra copies, only in groups where all six values are identical
BEGIN;
DELETE FROM energy_readings e
USING (
    SELECT r.tableoid AS chunk_oid, r.ctid,
           row_number() OVER (PARTITION BY r.meter_id, r.event_time
                              ORDER BY r.ctid) AS copy_no
    FROM energy_readings r
    JOIN dup_groups g USING (meter_id, event_time)
    WHERE g.distinct_versions = 1
) d
WHERE e.tableoid = d.chunk_oid
  AND e.ctid     = d.ctid
  AND d.copy_no  > 1;
COMMIT;

-- 4. AFTER cleaning: compare with before and with the reference count
SELECT 'after cleaning' AS stage, count(*) AS row_count,
       round(sum(energy_kwh)::numeric, 6) AS total_energy_kwh
FROM energy_readings;

\x on
SELECT b.row_count                                         AS rows_before,
       a.row_count                                         AS rows_after,
       b.row_count - a.row_count                           AS rows_deleted,
       a.row_count = 10643735                              AS matches_unique_readings,
       round(b.total_energy_kwh::numeric, 6)               AS energy_before_kwh,
       round(a.total_energy::numeric, 6)                   AS energy_after_kwh,
       round((b.total_energy_kwh - a.total_energy)::numeric, 6) AS energy_removed_kwh,
       round((SELECT sum(extra_energy_kwh) FROM dup_groups
              WHERE distinct_versions = 1)::numeric, 6)    AS energy_of_extra_copies_kwh
FROM clean_before b,
     (SELECT count(*) AS row_count, sum(energy_kwh) AS total_energy
      FROM energy_readings) a;
\x off

-- No duplicate pairs may remain
SELECT count(*) AS remaining_duplicate_pairs
FROM (SELECT 1 FROM energy_readings
      GROUP BY meter_id, event_time HAVING count(*) > 1) t;

-- 5. Reclaim the deleted rows' space and refresh planner statistics
VACUUM ANALYZE energy_readings;