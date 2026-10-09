-- 1.1 Create the assignment database and enable TimescaleDB
CREATE DATABASE smart_grid;
\connect smart_grid
CREATE EXTENSION IF NOT EXISTS timescaledb;
ALTER DATABASE smart_grid SET timezone TO 'Africa/Kigali';
SET timezone TO 'Africa/Kigali';

-- Checks for time
SELECT current_database(), now() AS cat_now;
SELECT extname, extversion FROM pg_extension WHERE extname = 'timescaledb';
SHOW timezone;
SELECT date_trunc('day', now()) AS cat_midnight_today;