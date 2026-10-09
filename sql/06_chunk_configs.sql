-- 3.1 Build two more chunk configurations from the cleaned energy_readings (1-day chunks).
-- Repeatable: drops and rebuilds the two copies. energy_readings itself is never dropped.
\timing on

DROP TABLE IF EXISTS energy_readings_3h;
DROP TABLE IF EXISTS energy_readings_week;

-- Same eight columns as energy_readings
CREATE TABLE energy_readings_3h (
    meter_id      BIGINT,
    event_time    TIMESTAMPTZ NOT NULL,
    received_time TIMESTAMPTZ,
    power_kw      DOUBLE PRECISION,
    voltage_v     DOUBLE PRECISION,
    current_a     DOUBLE PRECISION,
    frequency_hz  DOUBLE PRECISION,
    energy_kwh    DOUBLE PRECISION
);
CREATE TABLE energy_readings_week (LIKE energy_readings_3h INCLUDING ALL);

-- Hypertables partitioned by event_time; default index off so we create identical indexes ourselves
SELECT create_hypertable('energy_readings_3h',
                         by_range('event_time', INTERVAL '3 hours'),
                         create_default_indexes => FALSE);
SELECT create_hypertable('energy_readings_week',
                         by_range('event_time', INTERVAL '7 days'),
                         create_default_indexes => FALSE);

-- Copy the cleaned rows (load first, index afterwards: faster)
INSERT INTO energy_readings_3h   SELECT * FROM energy_readings;
INSERT INTO energy_readings_week SELECT * FROM energy_readings;

-- Index 1: event_time DESC (energy_readings already has this from create_hypertable)
CREATE INDEX IF NOT EXISTS energy_readings_3h_event_time_idx
    ON energy_readings_3h   USING btree (event_time DESC);
CREATE INDEX IF NOT EXISTS energy_readings_week_event_time_idx
    ON energy_readings_week USING btree (event_time DESC);

-- Index 2: meter_id, then event_time DESC, on all three tables
CREATE INDEX IF NOT EXISTS energy_readings_meter_time_idx
    ON energy_readings      USING btree (meter_id, event_time DESC);
CREATE INDEX IF NOT EXISTS energy_readings_3h_meter_time_idx
    ON energy_readings_3h   USING btree (meter_id, event_time DESC);
CREATE INDEX IF NOT EXISTS energy_readings_week_meter_time_idx
    ON energy_readings_week USING btree (meter_id, event_time DESC);

-- Fresh planner statistics for the benchmarks (required by 3.2.1)
ANALYZE energy_readings;
ANALYZE energy_readings_3h;
ANALYZE energy_readings_week;