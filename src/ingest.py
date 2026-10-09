"""2.1 Capture the full generator stream to CSV, then bulk-load it into energy_readings with COPY.

  python src\\ingest.py            generate the CSV, then load it
  python src\\ingest.py generate   only write the CSV
  python src\\ingest.py load       only load an existing CSV
"""
import csv
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))            # generator
sys.path.insert(0, str(ROOT / "src"))    # db.py
import smart_meter_simulator as sim
from db import connect

CSV_PATH = ROOT / "data" / "energy_readings.csv"
RESULT_PATH = ROOT / "results" / "2.1_ingest.json"
FIELDS = ("meter_id", "event_time", "received_time", "power_kw",
          "voltage_v", "current_a", "frequency_hz", "energy_kwh")
PROGRESS_EVERY = 500_000
CAT = timezone(timedelta(hours=2), "CAT")


def now():
    return datetime.now(CAT).strftime("%Y-%m-%d %H:%M:%S CAT")


# ---------------- phase 1: generator -> CSV ----------------
def generate(expected):
    print(f"[{now()}] Generation started -> {CSV_PATH}")
    CSV_PATH.parent.mkdir(exist_ok=True)
    start = time.perf_counter()
    consumed = 0
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)                       # header line
        for reading in sim.iter_readings():          # one reading at a time
            writer.writerow([reading[k] for k in FIELDS])
            consumed += 1
            if consumed % PROGRESS_EVERY == 0:
                secs = time.perf_counter() - start
                print(f"  {consumed:>12,} / {expected:,} "
                      f"({100 * consumed / expected:5.1f} %)  {secs:6.0f} s")
    seconds = time.perf_counter() - start
    print(f"[{now()}] Generation finished: {consumed:,} dictionaries consumed "
          f"in {seconds:.1f} s ({CSV_PATH.stat().st_size / 1024**3:.2f} GB)")
    return consumed, seconds


# ---------------- phase 2: CSV -> PostgreSQL ----------------
class ProgressFile:
    """Wraps the CSV file and prints how much of it COPY has read."""
    def __init__(self, f, total_bytes):
        self.f, self.total, self.done, self.next = f, total_bytes, 0, 0.1

    def read(self, size=-1):
        data = self.f.read(size)
        self.done += len(data)
        if self.done / self.total >= self.next:
            print(f"  COPY has read {100 * self.done / self.total:5.1f} % of the file")
            self.next += 0.1
        return data

    def readline(self, size=-1):
        return self.f.readline(size)


def load():
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM energy_readings")
    existing = cur.fetchone()[0]
    if existing:
        sys.exit(f"energy_readings already has {existing:,} rows. "
                 f"Empty it first with: TRUNCATE energy_readings;")

    print(f"[{now()}] Load started (COPY into energy_readings)")
    start = time.perf_counter()                      # first database write
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        cur.copy_expert(
            f"COPY energy_readings ({', '.join(FIELDS)}) FROM STDIN WITH (FORMAT csv, HEADER true)",
            ProgressFile(f, CSV_PATH.stat().st_size), size=1024 * 1024)
    conn.commit()                                    # final commit
    seconds = time.perf_counter() - start
    cur.execute("SELECT count(*) FROM energy_readings")
    committed = cur.fetchone()[0]
    conn.close()
    print(f"[{now()}] Load committed: {committed:,} rows in {seconds:.1f} s")
    return committed, seconds


def count_csv_rows():
    """Independent recount of data rows in the file (all lines minus the header)."""
    with open(CSV_PATH, "rb") as f:
        return sum(1 for _ in f) - 1


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    info = sim.dataset_info()
    expected = info["expected_counts"]["emitted_readings"]
    print("dataset_info():")
    print(json.dumps(info, indent=2))

    result = {"route": "generator -> CSV file -> PostgreSQL COPY",
              "started": now(), "dataset_info": info}
    total_start = time.perf_counter()

    if mode in ("all", "generate"):
        result["dictionaries_consumed"], result["generation_seconds"] = generate(expected)
    if mode in ("all", "load"):
        result["rows_committed"], result["load_seconds"] = load()
    if mode == "all":
        result["total_seconds"] = time.perf_counter() - total_start
        print(f"Total elapsed (generation start -> final commit): {result['total_seconds']:.1f} s")

    print(f"[{now()}] Recounting CSV data rows ...")
    result["csv_data_rows"] = count_csv_rows()
    result["finished"] = now()

    print("\n================ COUNT CHECK ================")
    checks = [("expected emitted_readings", expected),
              ("dictionaries consumed", result.get("dictionaries_consumed")),
              ("CSV data rows", result["csv_data_rows"]),
              ("energy_readings rows", result.get("rows_committed"))]
    for name, value in checks:
        print(f"  {name:<27}: {value:>12,}" if value is not None else f"  {name:<27}: (not run)")
    values = [v for _, v in checks if v is not None]
    result["all_match"] = len(set(values)) == 1
    print("  RESULT:", "ALL MATCH" if result["all_match"] else "MISMATCH - investigate!")

    RESULT_PATH.write_text(json.dumps(result, indent=2))
    print(f"Saved {RESULT_PATH}")


if __name__ == "__main__":
    main()