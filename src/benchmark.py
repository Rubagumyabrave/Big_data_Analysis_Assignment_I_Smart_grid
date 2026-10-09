"""3.2 / 4.3 Benchmark Q1-Q5: 1 warm-up + 5 measured runs per query and table (warm cache).

  python src\\benchmark.py chunks energy_readings_3h energy_readings energy_readings_week

The first argument is a tag used in the output file names; the rest are the tables.
"""
import csv
import json
import socket
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import ROOT, connect
from queries import QUERIES

CAT = timezone(timedelta(hours=2), "CAT")
MACHINE = socket.gethostname()
CLIENT = f"psycopg2 {psycopg2.__version__.split()[0]} (Python {sys.version.split()[0]})"
TIMER = "Python time.perf_counter, from execute() to fetchall() returning the last row"
WARMUPS, MEASURED = 1, 5
TOLERANCE = 0.001


def cat_now():
    return datetime.now(CAT).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def results_match(a, b):
    """Same rows in the same order; numbers may differ by at most TOLERANCE."""
    if len(a) != len(b):
        return False
    for row_a, row_b in zip(a, b):
        for x, y in zip(row_a, row_b):
            if isinstance(x, (float, Decimal)) or isinstance(y, (float, Decimal)):
                if abs(float(x) - float(y)) > TOLERANCE:
                    return False
            elif x != y:
                return False
    return True


def main():
    tag, tables = sys.argv[1], sys.argv[2:]
    out = ROOT / "results"
    out.mkdir(exist_ok=True)

    conn = connect()
    conn.autocommit = True
    cur = conn.cursor()

    runs, answers = [], {}
    print(f"Machine {MACHINE} | client {CLIENT}")
    print(f"Tables: {', '.join(tables)} | {WARMUPS} warm-up + {MEASURED} measured runs each\n")

    session_start_cat = cat_now()
    session_start = time.perf_counter()
    for query, sql in QUERIES.items():
        for table in tables:
            statement = sql.format(table=table)
            durations = []
            for i in range(WARMUPS + MEASURED):
                kind = "warm-up" if i < WARMUPS else "measured"
                start_cat = cat_now()
                t0 = time.perf_counter()
                cur.execute(statement)          # submit
                rows = cur.fetchall()           # last row received
                ms = (time.perf_counter() - t0) * 1000
                runs.append({"query": query, "table": table, "run": i, "kind": kind,
                             "start_cat": start_cat, "end_cat": cat_now(),
                             "duration_ms": round(ms, 3), "rows_returned": len(rows),
                             "machine": MACHINE})
                if kind == "measured":
                    durations.append(ms)
            answers[(query, table)] = rows
            print(f"  {query} {table:<26} median {statistics.median(durations):10.1f} ms  "
                  f"(min {min(durations):.1f}, max {max(durations):.1f}, rows {len(rows)})")
    session_seconds = time.perf_counter() - session_start
    session_end_cat = cat_now()

    # Correctness: every table must give the same answer as the first table
    print("\nResult check (each table vs " + tables[0] + ", tolerance 0.001):")
    checks = {}
    for query in QUERIES:
        ok = all(results_match(answers[(query, tables[0])], answers[(query, t)]) for t in tables)
        checks[query] = ok
        print(f"  {query}: {'MATCH' if ok else 'DIFFERENT - investigate!'}")

    # Summary: median / min / max of the measured runs
    summary = []
    for query in QUERIES:
        for table in tables:
            d = [r["duration_ms"] for r in runs
                 if r["query"] == query and r["table"] == table and r["kind"] == "measured"]
            summary.append({"query": query, "table": table,
                            "median_ms": round(statistics.median(d), 3),
                            "min_ms": round(min(d), 3), "max_ms": round(max(d), 3)})

    print("\nMEDIAN ms (warm cache)")
    print("  " + "query".ljust(7) + "".join(t.ljust(26) for t in tables))
    for query in QUERIES:
        line = "".join(f"{s['median_ms']:<26.1f}" for t in tables
                       for s in summary if s["query"] == query and s["table"] == t)
        print("  " + query.ljust(7) + line)
    print(f"\nSession: {session_start_cat} -> {session_end_cat} CAT = {session_seconds:.1f} s")

    # Save runs, summary and metadata
    with open(out / f"bench_{tag}_runs.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=runs[0].keys())
        writer.writeheader()
        writer.writerows(runs)
    with open(out / f"bench_{tag}_summary.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary[0].keys())
        writer.writeheader()
        writer.writerows(summary)
    meta = {"tag": tag, "tables": tables, "machine": MACHINE, "client": CLIENT, "timer": TIMER,
            "cache_state": "warm (1 warm-up run before 5 measured runs)",
            "session_start_cat": session_start_cat, "session_end_cat": session_end_cat,
            "session_seconds": round(session_seconds, 1), "results_match": checks}
    (out / f"bench_{tag}_meta.json").write_text(json.dumps(meta, indent=2))

    # Execution plans with actual timing and buffers (after timing, so they do not disturb it)
    print("\nSaving EXPLAIN (ANALYZE, BUFFERS) plans ...")
    with open(out / f"bench_{tag}_plans.txt", "w", encoding="utf-8") as f:
        for query, sql in QUERIES.items():
            for table in tables:
                cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + sql.format(table=table))
                f.write(f"===== {query} on {table} =====\n")
                f.write("\n".join(r[0] for r in cur.fetchall()) + "\n\n")
    conn.close()
    print(f"Saved bench_{tag}_runs.csv, bench_{tag}_summary.csv, "
          f"bench_{tag}_meta.json, bench_{tag}_plans.txt in results\\")


if __name__ == "__main__":
    main()