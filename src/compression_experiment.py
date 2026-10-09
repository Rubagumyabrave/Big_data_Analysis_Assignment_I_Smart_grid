"""4.1 Build energy_time_compressed and energy_meter_compressed (1-day chunks), copy the
cleaned data one chunk at a time, compress each chunk whose end is before the cutoff,
and time compression separately from loading. Every step is recorded in compression_log.

  python src\\compression_experiment.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect

BASELINE = "energy_readings"          # cleaned data, 1-day chunks (chosen in Section 3)
INTERVAL = "1 day"
CONFIGS = {
    "energy_time_compressed":  "timescaledb.orderby = 'event_time DESC'",
    "energy_meter_compressed": "timescaledb.orderby = 'event_time DESC', "
                               "timescaledb.segmentby = 'meter_id'",
}


def main():
    conn = connect()
    conn.autocommit = True
    cur = conn.cursor()

    # 4.1.4 One cutoff for the whole experiment: start time minus 48 hours
    cur.execute("SELECT now(), now() - INTERVAL '48 hours'")
    started, cutoff = cur.fetchone()
    print(f"Experiment start: {started:%Y-%m-%d %H:%M:%S%z}")
    print(f"Cutoff (start - 48 h): {cutoff:%Y-%m-%d %H:%M:%S%z}\n")

    # Log table, so the SQL checks can report times and row shares later
    cur.execute("""CREATE TABLE IF NOT EXISTS compression_log (
                       table_name text, chunk text,
                       range_start timestamptz, range_end timestamptz,
                       rows_loaded bigint, load_s double precision,
                       compressed boolean, compress_s double precision,
                       experiment_start timestamptz, cutoff timestamptz)""")
    cur.execute("DELETE FROM compression_log")

    # 4.1.1-4.1.3 Create both tables, same columns and indexes, columnstore settings, paused policy
    for table, settings in CONFIGS.items():
        cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute(f"CREATE TABLE {table} "
                    f"(LIKE {BASELINE} INCLUDING DEFAULTS INCLUDING CONSTRAINTS)")
        cur.execute(f"SELECT create_hypertable('{table}', "
                    f"by_range('event_time', INTERVAL '{INTERVAL}'), "
                    f"create_default_indexes => FALSE)")
        cur.execute(f"CREATE INDEX {table}_event_time_idx ON {table} "
                    f"USING btree (event_time DESC)")
        cur.execute(f"CREATE INDEX {table}_meter_time_idx ON {table} "
                    f"USING btree (meter_id, event_time DESC)")
        cur.execute(f"ALTER TABLE {table} SET (timescaledb.enable_columnstore = true, {settings})")
        cur.execute(f"CALL add_columnstore_policy('{table}', after => INTERVAL '48 hours')")
        cur.execute("SELECT job_id FROM timescaledb_information.jobs "
                    "WHERE hypertable_name = %s AND proc_name = 'policy_compression'", (table,))
        job_id = cur.fetchone()[0]
        cur.execute("SELECT alter_job(%s, scheduled => false)", (job_id,))   # pause
        print(f"Created {table}: {settings}; policy job {job_id} created and PAUSED")

    # The baseline's chunk ranges are the load units, so both tables get identical chunks
    cur.execute("SELECT range_start, range_end FROM timescaledb_information.chunks "
                "WHERE hypertable_name = %s ORDER BY range_start", (BASELINE,))
    ranges = cur.fetchall()

    # 4.1.5 Load one chunk at a time; compress it if its end is before the cutoff
    for table in CONFIGS:
        print(f"\n--- {table} ---")
        total_load = total_compress = 0.0
        for range_start, range_end in ranges:
            t0 = time.perf_counter()
            cur.execute(f"INSERT INTO {table} SELECT * FROM {BASELINE} "
                        "WHERE event_time >= %s AND event_time < %s", (range_start, range_end))
            rows = cur.rowcount
            load_s = time.perf_counter() - t0
            total_load += load_s

            cur.execute("SELECT format('%%I.%%I', chunk_schema, chunk_name) "
                        "FROM timescaledb_information.chunks "
                        "WHERE hypertable_name = %s AND range_start = %s", (table, range_start))
            chunk = cur.fetchone()[0]

            compressed, compress_s = False, None
            if range_end < cutoff:
                t1 = time.perf_counter()
                cur.execute("CALL convert_to_columnstore(%s)", (chunk,))
                compress_s = time.perf_counter() - t1
                total_compress += compress_s
                compressed = True

            cur.execute("INSERT INTO compression_log VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (table, chunk, range_start, range_end, rows, load_s,
                         compressed, compress_s, started, cutoff))
            print(f"  {range_start:%Y-%m-%d %H:%M}  rows={rows:>8,}  load={load_s:6.2f} s  "
                  f"compress={'%.2f s' % compress_s if compressed else 'not compressed'}")

        cur.execute(f"ANALYZE {table}")
        print(f"  TOTAL {table}: load {total_load:.1f} s, compression {total_compress:.1f} s")

    conn.close()
    print("\nDone. Per-chunk details are in the compression_log table.")


if __name__ == "__main__":
    main()