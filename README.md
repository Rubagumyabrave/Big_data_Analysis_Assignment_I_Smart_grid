# Smart Energy Grid Analytics (Advanced Big Data Analytics, Assignment I)

MQTT ingestion, TimescaleDB storage experiments, consumption analysis, continuous aggregates,
Grafana dashboards and a day-ahead forecast, built on the supplied generator
`smart_meter_simulator.py` (included unchanged).

All commands are for **Windows cmd**, run from the project folder with the virtual
environment active. All dates and times are CAT (Africa/Kigali).

## 1. Requirements

| Component | Version used |
|---|---|
| Windows 10 Pro + Docker Desktop (WSL2) | 19045 |
| PostgreSQL + TimescaleDB (Docker image `timescale/timescaledb:latest-pg17`) | 17.11 + 2.30.2 |
| EMQX (Docker image `emqx/emqx:latest`) | 6.3.1 |
| Grafana OSS (Docker image `grafana/grafana-oss:latest`) | latest |
| Python | 3.11.9 |
| Google Chrome (only for 7.4 dashboard timing) | any recent |

About 10 GB of free disk space is needed (the CSV is about 1.2 GB and the database tables about 4 GB).

## 2. Project layout

```
smart_meter_simulator.py   supplied generator (unchanged)
requirements.txt           Python packages (pip freeze)
.env.example               connection settings template (copy to .env)
sql/                       SQL scripts 01-13, run in order
src/                       Python programs (db.py is the shared connection helper)
grafana/provisioning/      Grafana data source and the Raw / Aggregate dashboards
results/                   recorded outputs: summaries (*.md), timings (*.csv/*.json), logs
results/figures/           charts produced by the analysis and forecast scripts
report/                    the assignment report
data/                      NOT committed: generated CSV and forecast files (recreated by the scripts)
```

## 3. One-time setup

**3.1 Python environment**

```cmd
cd /d "D:\path\to\Assignment_I"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**3.2 Connection settings.** Copy the template and put your own passwords in `.env`
(the file is ignored by git):

```cmd
copy .env.example .env
notepad .env
```

**3.3 Start the database and the broker** (replace `<your_postgres_password>` with the value in `.env`):

```cmd
docker run -d --name timescaledb -p 5432:5432 -e POSTGRES_PASSWORD=<your_postgres_password> timescale/timescaledb:latest-pg17
docker run -d --name emqx -p 1883:1883 -p 8083:8083 -p 18083:18083 emqx/emqx:latest
docker ps
```

If the containers already exist, start them with `docker start timescaledb emqx`.
The EMQX dashboard is at http://localhost:18083.

**3.4 Create the database and tables** (`01` runs only once, because it creates the database):

```cmd
docker exec -i timescaledb psql -U postgres -d postgres < sql\01_create_database.sql
docker exec -i timescaledb psql -U postgres -d smart_grid < sql\02_schema.sql
python src\load_meters.py
```

Expected: `timescaledb` extension enabled, time zone `Africa/Kigali`, `meters` = 4,000 rows.

## 4. Pilot stream (Section 1.3) - verifies the four counts

Use **two cmd windows**, both in the project folder with `.venv` active.

**Window 1 - start the subscriber first.** It empties `energy_live`, subscribes to
`energy/meters/#` at QoS 1 and waits:

```cmd
python src\subscriber.py
```

Wait until it prints `READY - start the publisher now`.

**Window 2 - publish the first 2,000 readings** (QoS 1, no retain, paced at 300 messages/s):

```cmd
python src\publisher.py
```

The subscriber stops by itself after 2,000 messages (or 15 s without messages). Then check the database:

```cmd
docker exec timescaledb psql -U postgres -d smart_grid -c "SELECT count(*) FROM energy_live;"
```

**Expected result - 2,000 at every stage:**

| Count | Where to read it |
|---|---|
| Dictionaries taken from the generator | publisher output / `results\pilot_publisher.log` |
| Messages acknowledged by the broker | publisher output / `results\pilot_publisher.log` |
| Messages received by the subscriber | subscriber output / `results\pilot_subscriber.log` |
| Rows in `energy_live` | the SQL count above |

The 2,000 rows include 6 deliberate generator duplicates (1,994 unique meter/time pairs).

## 5. Full execution order

SQL files are run with `docker exec -i timescaledb psql -U postgres -d smart_grid < sql\<file>`
(shortened to **SQL `<file>`** below). Python files are run with `python src\<file>`.

| Step | Section | Command(s) | Output |
|---|---|---|---|
| 1 | 2.1 Load | `python src\ingest.py` (generate CSV + COPY), then SQL `03_load_checks.sql` | `data\energy_readings.csv`, `results\2.1_ingest.json` |
| 2 | 2.2 Quality | SQL `04_data_quality.sql` | counts vs reference |
| 3 | 2.3 Cleaning | SQL `05_clean_duplicates.sql` | 10,643,735 rows |
| 4 | 3.1 Chunks | SQL `06_chunk_configs.sql`, SQL `07_chunk_checks.sql` | 3h / 1d / 7d tables |
| 5 | 3.2 Benchmark | `python src\benchmark.py chunks energy_readings_3h energy_readings energy_readings_week`, SQL `08_plans_q1.sql` | `results\bench_chunks_*` |
| 6 | 4.1-4.2 Compression | `python src\compression_experiment.py`, SQL `09_compression_checks.sql` | compressed tables, storage |
| 7 | 4.3 Benchmark | `python src\benchmark.py compression energy_readings energy_time_compressed energy_meter_compressed`, SQL `10_plans_q4.sql` | `results\bench_compression_*` |
| 8 | 4.3 Resume policies | SQL `11_resume_compression_policies.sql` | jobs scheduled again |
| 9 | 5.1-5.4 Analysis | `python src\analysis_5_1.py`, `analysis_5_2.py`, `analysis_5_3.py`, `analysis_5_4.py` | `results\5_*.csv`, `results\figures\5_*.png` |
| 10 | 6.1 Aggregates | SQL `12_continuous_aggregates.sql`, `python src\caggs_refresh.py`, SQL `13_caggs_evidence.sql` | `results\6_1_caggs_refresh.json` |
| 11 | 6.2 Freshness | `python src\freshness_test.py` | `results\6_2_freshness_test.txt` |
| 12 | 7.1-7.2 Dashboards | `python src\dashboards.py`, then start Grafana (below) | `grafana\provisioning\dashboards\*.json` |
| 13 | 7.3 Verify | `python src\verify_dashboards.py` | `results\7.3_dashboard_verification.csv` |
| 14 | 7.4 Timing | `python src\dashboard_timing.py` (pauses and resumes jobs itself) | `results\7.4_dashboard_timing_*` |
| 15 | 8.1-8.4 Forecast | `python src\forecast_8_1_dataset.py`, `forecast_8_2_baseline.py`, `forecast_8_3_model.py`, `forecast_8_4_evaluate.py` | `results\8_*`, `results\figures\8_4_forecast_region1.png` |

**Start Grafana** (step 12; replace both placeholders with the values in `.env`). Then open
http://localhost:3000 and choose the dashboards **Raw** and **Aggregate**:

```cmd
docker run -d --name grafana_smartgrid -p 3000:3000 ^
  -e GF_SECURITY_ADMIN_PASSWORD=<your_grafana_admin_password> ^
  -e PGPASSWORD=<your_postgres_password> ^
  -e TZ=Africa/Kigali ^
  -v "%cd%\grafana\provisioning:/etc/grafana/provisioning" ^
  --add-host host.docker.internal:host-gateway ^
  grafana/grafana-oss:latest
```

## 6. Regenerating the dataset

The full dataset (10,696,848 readings, about 1.2 GB as CSV) is **not** in the repository. It is
recreated exactly by the unchanged generator:

| Command | What it does |
|---|---|
| `python src\ingest.py` | write `data\energy_readings.csv`, then COPY it into `energy_readings` |
| `python src\ingest.py generate` | only write the CSV |
| `python src\ingest.py load` | only COPY an existing CSV |

Load into an empty `energy_readings` table (run `sql\02_schema.sql` on a fresh database first).

## 7. Notes

- Passwords and connection secrets live only in `.env` (ignored by git); `.env.example` holds placeholders.
- Benchmarks use 1 warm-up + 5 measured runs and report medians; recorded timings are in `results\`.
- `sql\05_clean_duplicates.sql` is repeatable: a second run deletes 0 rows.
