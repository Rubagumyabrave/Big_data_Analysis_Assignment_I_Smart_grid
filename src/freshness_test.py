"""6.2 Freshness and delayed arrivals test on a separate hypertable and hourly continuous
aggregate (real-time off, no refresh policy).

  python src\\freshness_test.py
"""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import ROOT, connect

LOG = []


def log(text=""):
    print(text)
    LOG.append(text)


def fmt(ts):
    return ts.strftime("%Y-%m-%d %H:%M:%S") + " CAT"


SETUP = [
    "DROP MATERIALIZED VIEW IF EXISTS freshness_hourly",
    "DROP TABLE IF EXISTS freshness_test",
    """CREATE TABLE freshness_test (
           event_time TIMESTAMPTZ NOT NULL,
           energy_kwh DOUBLE PRECISION)""",
    "SELECT create_hypertable('freshness_test', by_range('event_time', INTERVAL '1 day'))",
    """CREATE MATERIALIZED VIEW freshness_hourly
       WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
       SELECT time_bucket(INTERVAL '1 hour', event_time, 'Africa/Kigali') AS bucket,
              sum(energy_kwh) AS energy_kwh,
              count(*)        AS row_count
       FROM freshness_test
       GROUP BY bucket
       WITH NO DATA""",
]

RAW = """
SELECT h.label, h.hour_start, coalesce(sum(t.energy_kwh), 0) AS energy_kwh, count(t.event_time) AS row_count
FROM (VALUES ('older hour', %s::timestamptz), ('hour H', %s::timestamptz)) AS h(label, hour_start)
LEFT JOIN freshness_test t
       ON t.event_time >= h.hour_start AND t.event_time < h.hour_start + INTERVAL '1 hour'
GROUP BY h.label, h.hour_start
ORDER BY h.hour_start"""

AGG = """
SELECT h.label, h.hour_start, a.energy_kwh, a.row_count
FROM (VALUES ('older hour', %s::timestamptz), ('hour H', %s::timestamptz)) AS h(label, hour_start)
LEFT JOIN freshness_hourly a ON a.bucket = h.hour_start
ORDER BY h.hour_start"""


def show(cur, title, sql, older, h_start):
    cur.execute(sql, (older, h_start))
    log(f"  {title}")
    for label, start, kwh, rows in cur.fetchall():
        if kwh is None:
            log(f"    {label:<10} {fmt(start)}: no bucket returned")
        else:
            log(f"    {label:<10} {fmt(start)}: {float(kwh):.1f} kWh, {rows} row(s)")


def insert(cur, event_time, kwh):
    cur.execute("INSERT INTO freshness_test VALUES (%s, %s)", (event_time, kwh))
    cur.execute("SELECT now()")
    log(f"  INSERT event_time={fmt(event_time)} energy_kwh={kwh}  (at {fmt(cur.fetchone()[0])})")


def realtime_setting(cur):
    cur.execute("SELECT materialized_only FROM timescaledb_information.continuous_aggregates "
                "WHERE view_name = 'freshness_hourly'")
    return cur.fetchone()[0]


def main():
    conn = connect()
    conn.autocommit = True               # refresh_continuous_aggregate needs autocommit
    cur = conn.cursor()

    # ---- setup ----
    for sql in SETUP:
        cur.execute(sql)
    log("SETUP: hypertable freshness_test (event_time TIMESTAMPTZ, energy_kwh DOUBLE PRECISION)")
    log("       continuous aggregate freshness_hourly: hourly CAT bucket, sum(energy_kwh), count(*),")
    log("       WITH NO DATA, materialized_only = true; no refresh policy")
    cur.execute("SELECT count(*) FROM timescaledb_information.jobs WHERE hypertable_name IN "
                "(SELECT materialization_hypertable_name FROM timescaledb_information.continuous_aggregates "
                " WHERE view_name = 'freshness_hourly')")
    log(f"       refresh policies on freshness_hourly: {cur.fetchone()[0]}; "
        f"materialized_only = {realtime_setting(cur)}")

    # ---- times ----
    cur.execute("SELECT now(), date_trunc('hour', now(), 'Africa/Kigali') - INTERVAL '1 hour'")
    test_time, h_start = cur.fetchone()
    older = h_start - timedelta(hours=48)
    log(f"\nTest time (CAT)          : {fmt(test_time)}")
    log(f"H (last completed hour)  : {fmt(h_start)} to {fmt(h_start + timedelta(hours=1))}")
    log(f"Older hour (H - 48 h)    : {fmt(older)} to {fmt(older + timedelta(hours=1))}")
    e1, e2, e3 = older + timedelta(minutes=10), older + timedelta(minutes=25), h_start + timedelta(minutes=10)
    log(f"Chosen event_times       : 1 kWh at {fmt(e1)}, 0.5 kWh at {fmt(e2)}, 2 kWh at {fmt(e3)}")

    # ---- stage 1 ----
    log("\nSTAGE 1: insert 1 kWh into the older hour, refresh ONLY the older hour (real-time off)")
    insert(cur, e1, 1.0)
    cur.execute("CALL refresh_continuous_aggregate('freshness_hourly', %s, %s)",
                (older, older + timedelta(hours=1)))
    log(f"  CALL refresh_continuous_aggregate(older hour) done; materialized_only = {realtime_setting(cur)}")
    show(cur, "Aggregate:", AGG, older, h_start)

    # ---- stage 2 ----
    log("\nSTAGE 2: insert 0.5 kWh into the older hour and 2 kWh into hour H (no refresh, real-time off)")
    insert(cur, e2, 0.5)
    insert(cur, e3, 2.0)
    show(cur, "Raw table:", RAW, older, h_start)
    show(cur, "Aggregate:", AGG, older, h_start)

    # ---- stage 3 ----
    log("\nSTAGE 3: enable real-time aggregation (still no refresh)")
    cur.execute("ALTER MATERIALIZED VIEW freshness_hourly SET (timescaledb.materialized_only = false)")
    log(f"  ALTER MATERIALIZED VIEW ... materialized_only = false -> now {realtime_setting(cur)}")
    show(cur, "Aggregate (real-time on):", AGG, older, h_start)

    # ---- stage 4 ----
    log("\nSTAGE 4: manually refresh both complete hours, then query with real-time off again")
    cur.execute("CALL refresh_continuous_aggregate('freshness_hourly', %s, %s)",
                (older, h_start + timedelta(hours=1)))
    cur.execute("ALTER MATERIALIZED VIEW freshness_hourly SET (timescaledb.materialized_only = true)")
    log(f"  CALL refresh_continuous_aggregate(older hour .. end of H) done; "
        f"materialized_only = {realtime_setting(cur)} (stored results only)")
    show(cur, "Raw table:", RAW, older, h_start)
    show(cur, "Aggregate:", AGG, older, h_start)

    # ---- checks ----
    cur.execute(AGG, (older, h_start))
    final = {label: (float(k), r) for label, _, k, r in cur.fetchall()}
    ok = final["older hour"] == (1.5, 2) and final["hour H"] == (2.0, 1)
    log(f"\nCHECK older hour = 1.5 kWh / 2 rows and hour H = 2 kWh / 1 row: {'PASS' if ok else 'FAIL'}")

    # ---- which hours could the 6.1 policy refresh at the test time? ----
    win_start = test_time - timedelta(days=3)
    win_end = test_time - timedelta(hours=1)
    log(f"\n6.1 policy window at the test time: {fmt(win_start)} to {fmt(win_end)} "
        "(start_offset 3 days, end_offset 1 hour)")
    for label, start in (("older hour", older), ("hour H", h_start)):
        inside = start >= win_start and start + timedelta(hours=1) <= win_end
        log(f"  {label:<10} {fmt(start)}: {'could be refreshed' if inside else 'NOT refreshable yet'}"
            f" (bucket {'fully inside' if inside else 'not fully inside'} the window)")
    log(f"  Hour H becomes refreshable from {fmt(h_start + timedelta(hours=2))} "
        "(one hour after it ends).")

    conn.close()
    (ROOT / "results" / "6_2_freshness_test.txt").write_text("\n".join(LOG), encoding="utf-8")
    print("\nSaved results\\6_2_freshness_test.txt")


if __name__ == "__main__":
    main()