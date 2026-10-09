# 1.1 Environment

Recorded 2026-10-08 (CAT). Evidence: 1.1_a_broker_running.png, 1.1_b_database_extension_timezone.png, 1.1_c_environment_2.png

| Item | Value |
|---|---|
| CPU | Intel(R) Core(TM) i7-6600U @ 2.60GHz, 2 cores / 4 logical processors |
| RAM (host) | 15,784 MB (about 15.4 GB) |
| OS | Windows 10 Pro, version 10.0.19045 |
| Storage | Intel SSD (C:, holds Docker Desktop data, so all database files); Seagate HDD (D:, project folder and generated CSV) |
| Python | 3.11.9 (project virtual environment .venv) |
| EMQX | EMQX Enterprise 6.3.1 (Docker container `emqx`) |
| PostgreSQL | 17.11 (x86_64-pc-linux-musl, Alpine), Docker container `timescaledb` |
| TimescaleDB | 2.30.2 |
| shared_buffers | 1911MB |
| work_mem | 15294kB |
| max_parallel_workers_per_gather | 2 |
| jit | off |

Deployment: PostgreSQL/TimescaleDB and EMQX run in Docker containers inside the Docker Desktop
WSL2 virtual machine, which has 4 CPUs and 8,018,735,104 bytes (7.47 GiB) of RAM. No per-container
CPU or memory limits are set (`docker inspect timescaledb`: NanoCpus = 0, Memory = 0), so the
containers share the whole VM.

Database: `smart_grid`, TimescaleDB extension enabled, database time zone set with
`ALTER DATABASE smart_grid SET timezone = 'Africa/Kigali'`; daily buckets use
time_bucket(..., 'Africa/Kigali') so they align with CAT midnight. The Windows clock is synchronised
automatically; all times in this report are CAT.
