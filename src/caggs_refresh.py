"""6.1 Manually refresh each (initially empty) continuous aggregate over the whole period,
record refresh duration and materialized data/index size, THEN add refresh policies.

  python src\\caggs_refresh.py
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import ROOT, connect
from analysis_5_1 import CAT

VIEWS = ("energy_15min_region", "energy_hourly_region", "energy_daily_meter")
START, END = "2026-09-01 00:00:00+02", "2026-09-29 00:00:00+02"   # whole generated period

SIZE = """
SELECT table_bytes + toast_bytes, index_bytes, total_bytes
FROM hypertable_detailed_size(
    (SELECT format('%%I.%%I', materialization_hypertable_schema,
                   materialization_hypertable_name)::regclass
     FROM timescaledb_information.continuous_aggregates WHERE view_name = %s))"""


def now():
    return datetime.now(CAT).strftime("%Y-%m-%d %H:%M:%S")


def main():
    conn = connect()
    conn.autocommit = True        # refresh_continuous_aggregate cannot run inside a transaction
    cur = conn.cursor()
    results = {}
    print(f"[{now()} CAT] Manual refresh of {START} to {END}\n")

    for view in VIEWS:
        cur.execute(f"SELECT count(*) FROM {view}")
        before = cur.fetchone()[0]
        started = now()
        t0 = time.perf_counter()
        cur.execute("CALL refresh_continuous_aggregate(%s, %s::timestamptz, %s::timestamptz)",
                    (view, START, END))
        seconds = time.perf_counter() - t0
        cur.execute(f"SELECT count(*) FROM {view}")
        after = cur.fetchone()[0]
        cur.execute(SIZE, (view,))
        data_b, index_b, total_b = cur.fetchone()
        results[view] = {"rows_before": before, "rows_after": after,
                         "refresh_start_cat": started, "refresh_end_cat": now(),
                         "refresh_seconds": round(seconds, 2),
                         "data_mb": round(data_b / 2**20, 2),
                         "index_mb": round(index_b / 2**20, 2),
                         "total_mb": round(total_b / 2**20, 2)}
        r = results[view]
        print(f"{view:<22} rows {before} -> {after:>8,}   refresh {seconds:6.2f} s   "
              f"data {r['data_mb']:6.2f} MB   index {r['index_mb']:6.2f} MB   total {r['total_mb']:6.2f} MB")

    total_s = sum(r["refresh_seconds"] for r in results.values())
    total_mb = sum(r["total_mb"] for r in results.values())
    print(f"\nAll three: refresh {total_s:.2f} s, storage {total_mb:.2f} MB")

    # Only after the measurements: add the refresh policies
    print(f"\n[{now()} CAT] Adding refresh policies (start_offset 3 days, end_offset 1 hour, every 15 minutes)")
    for view in VIEWS:
        cur.execute("SELECT add_continuous_aggregate_policy(%s, "
                    "start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour', "
                    "schedule_interval => INTERVAL '15 minutes', if_not_exists => true)", (view,))
        results[view]["policy_job_id"] = cur.fetchone()[0]
        print(f"  {view:<22} policy job {results[view]['policy_job_id']}")

    (ROOT / "results" / "6_1_caggs_refresh.json").write_text(json.dumps(results, indent=2))
    conn.close()
    print("\nSaved results\\6_1_caggs_refresh.json")


if __name__ == "__main__":
    main()