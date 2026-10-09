-- 1.2 Create the three tables

-- Regular table for the live MQTT pilot (1.3)
CREATE TABLE IF NOT EXISTS energy_live (
    meter_id      BIGINT,
    event_time    TIMESTAMPTZ,
    received_time TIMESTAMPTZ,
    power_kw      DOUBLE PRECISION,
    voltage_v     DOUBLE PRECISION,
    current_a     DOUBLE PRECISION,
    frequency_hz  DOUBLE PRECISION,
    energy_kwh    DOUBLE PRECISION
);

-- Historical readings: same eight columns, then turned into a hypertable
CREATE TABLE IF NOT EXISTS energy_readings (
    meter_id      BIGINT,
    event_time    TIMESTAMPTZ NOT NULL,
    received_time TIMESTAMPTZ,
    power_kw      DOUBLE PRECISION,
    voltage_v     DOUBLE PRECISION,
    current_a     DOUBLE PRECISION,
    frequency_hz  DOUBLE PRECISION,
    energy_kwh    DOUBLE PRECISION
);

SELECT create_hypertable('energy_readings',
                         by_range('event_time', INTERVAL '1 day'),
                         if_not_exists => TRUE);

-- Meter metadata
CREATE TABLE IF NOT EXISTS meters (
    meter_id      BIGINT PRIMARY KEY,
    region        TEXT,
    customer_type TEXT,
    base_power_kw DOUBLE PRECISION,
    power_factor  DOUBLE PRECISION
);