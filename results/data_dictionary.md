# 1.2 Data dictionary

Evidence: 1.2_a_tables_1.png, 1.2_a_tables_2.png, 1.2_c_meters_count.png, 1.2_d_meters_count.png
Schema file: sql\02_schema.sql. energy_readings is a hypertable on event_time with 1-day chunks.

## energy_live (regular table, MQTT pilot) and energy_readings (hypertable, full dataset)

Both tables have the same eight columns. Duplicates are allowed (no primary key).

| Column | PostgreSQL type | Meaning | Unit |
|---|---|---|---|
| meter_id | BIGINT | Smart meter identifier (1000000000-1000003999) | none |
| event_time | TIMESTAMPTZ | Start of the 15-minute reading interval (NOT NULL in energy_readings, partitioning column) | timestamp, CAT |
| received_time | TIMESTAMPTZ | Simulated time the reading arrived (not database insert time) | timestamp, CAT |
| power_kw | DOUBLE PRECISION | Average power over the interval | kW |
| voltage_v | DOUBLE PRECISION | Supply voltage | V |
| current_a | DOUBLE PRECISION | Current | A |
| frequency_hz | DOUBLE PRECISION | Grid frequency | Hz |
| energy_kwh | DOUBLE PRECISION | Energy consumed in the interval (about power_kw x 0.25 h) | kWh |

## meters (4,000 rows)

| Column | PostgreSQL type | Meaning | Unit |
|---|---|---|---|
| meter_id | BIGINT, PRIMARY KEY | Smart meter identifier | none |
| region | TEXT | Region 1 to Region 10 (400 meters each) | none |
| customer_type | TEXT | residential, commercial or industrial | none |
| base_power_kw | DOUBLE PRECISION | Meter's typical base load used by the generator | kW |
| power_factor | DOUBLE PRECISION | Ratio of real to apparent power (0.95 for all meters) | none (ratio) |

Loaded by src\load_meters.py from meter_metadata(); SELECT count(*) FROM meters = 4,000.
