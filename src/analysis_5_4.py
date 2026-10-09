"""5.4 Abnormal consumption: flag readings far from the meter's own median for the same
CAT time of day and day type, then evaluate the flags against anomaly_events().

Rule (decided before looking at the labels):
  baseline = median power_kw of the same meter, same 15-minute time of day, same day type
             (weekday / weekend) over all 28 days
  ratio    = power_kw / baseline
  flag     = ratio >= 2.0 (high)  or  ratio <= 0.3 (low)

  python src\\analysis_5_4.py
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import smart_meter_simulator as sim
from db import connect
from analysis_5_1 import BLUE, CAT, FIG, GRID, INK, MUTED, ORANGE, OUT, query, style

HIGH, LOW = 2.0, 0.3
TOTAL_METERS = 4000

# Same CAT time-of-day slot and day type, used to match readings to their baseline
SLOT = "(r.event_time AT TIME ZONE 'Africa/Kigali')::time"
WEEKEND = "(extract(isodow FROM r.event_time AT TIME ZONE 'Africa/Kigali') >= 6)"

BASELINE = f"""
CREATE TEMP TABLE anomaly_baseline AS
SELECT r.meter_id,
       {SLOT}    AS slot,
       {WEEKEND} AS weekend,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY r.power_kw) AS median_kw,
       count(*)  AS n_days
FROM energy_readings r
GROUP BY 1, 2, 3"""

JOIN_BASELINE = f"""
JOIN anomaly_baseline b
  ON b.meter_id = r.meter_id AND b.slot = {SLOT} AND b.weekend = {WEEKEND}"""

RATIO_DISTRIBUTION = f"""
SELECT min(r.power_kw / b.median_kw) AS min_ratio,
       percentile_cont(ARRAY[0.0001, 0.001, 0.01, 0.5, 0.99, 0.999, 0.9999])
           WITHIN GROUP (ORDER BY r.power_kw / b.median_kw) AS quantiles,
       max(r.power_kw / b.median_kw) AS max_ratio
FROM energy_readings r {JOIN_BASELINE}"""

FLAGS = f"""
SELECT r.meter_id, r.event_time, r.power_kw, b.median_kw,
       r.power_kw / b.median_kw AS ratio,
       CASE WHEN r.power_kw >= {HIGH} * b.median_kw THEN 'high' ELSE 'low' END AS flag_type
FROM energy_readings r {JOIN_BASELINE}
WHERE r.power_kw >= {HIGH} * b.median_kw
   OR r.power_kw <= {LOW}  * b.median_kw
ORDER BY r.meter_id, r.event_time"""

COUNT_IN_INTERVAL = """
SELECT count(*) FROM energy_readings
WHERE meter_id = %s AND event_time >= %s AND event_time < %s"""

DAY_SERIES = f"""
SELECT r.event_time, r.power_kw, b.median_kw
FROM energy_readings r {JOIN_BASELINE}
WHERE r.meter_id = %s AND r.event_time >= %s AND r.event_time < %s
ORDER BY r.event_time"""


def run(cur, sql, params=None):
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=cols)


def main():
    t0 = datetime.now(CAT)
    print(f"[{t0:%Y-%m-%d %H:%M:%S} CAT] 5.4 anomaly detection on cleaned energy_readings")
    print(f"Rule: ratio = power_kw / median(power_kw of same meter, CAT time of day, day type); "
          f"flag if ratio >= {HIGH} or <= {LOW}\n")
    conn = connect()
    cur = conn.cursor()

    # 1. Baselines (no labels used)
    cur.execute("DROP TABLE IF EXISTS anomaly_baseline")
    cur.execute(BASELINE)
    cur.execute("SELECT count(*), min(n_days), max(n_days) FROM anomaly_baseline")
    n_base, min_n, max_n = cur.fetchone()
    print(f"Baselines built: {n_base:,} (meter x time of day x day type), "
          f"{min_n}-{max_n} readings each")

    # 2. How far do readings normally sit from their baseline?
    dist = run(cur, RATIO_DISTRIBUTION).iloc[0]
    q = [float(v) for v in dist["quantiles"]]
    print("Ratio distribution over all readings:")
    print(f"  min {float(dist['min_ratio']):.3f} | 0.01% {q[0]:.3f} | 0.1% {q[1]:.3f} | 1% {q[2]:.3f} | "
          f"median {q[3]:.3f} | 99% {q[4]:.3f} | 99.9% {q[5]:.3f} | 99.99% {q[6]:.3f} | "
          f"max {float(dist['max_ratio']):.3f}\n")

    # 3. Apply the rule
    flags = run(cur, FLAGS)
    flags["ratio"] = flags["ratio"].astype(float)
    cur.execute("SELECT count(*) FROM energy_readings")
    observed = cur.fetchone()[0]
    print(f"Flagged readings: {len(flags):,} of {observed:,} "
          f"({(flags.flag_type == 'high').sum():,} high, {(flags.flag_type == 'low').sum():,} low) "
          f"on {flags.meter_id.nunique()} meters")
    print("First 10 flagged readings:")
    show = flags.head(10).copy()
    show["event_time"] = [t.strftime("%Y-%m-%d %H:%M") for t in show["event_time"]]
    print(show.to_string(index=False, formatters={"power_kw": "{:.4f}".format,
                                                  "median_kw": "{:.4f}".format,
                                                  "ratio": "{:.3f}".format}))

    # 4. Only now load the labels and evaluate
    events = []
    for i, e in enumerate(sim.anomaly_events(), start=1):
        start = datetime.fromisoformat(e["start_time"])
        end = datetime.fromisoformat(e["end_time"])
        cur.execute(COUNT_IN_INTERVAL, (e["meter_id"], start, end))
        events.append({"event": i, "meter_id": e["meter_id"], "event_type": e["event_type"],
                       "start": start, "end": end, "readings_in_interval": cur.fetchone()[0]})
    ev = pd.DataFrame(events)

    def inside_any_event(row):
        same = ev[ev.meter_id == row.meter_id]
        return bool(((same.start <= row.event_time) & (row.event_time < same.end)).any())

    flags["in_event"] = flags.apply(inside_any_event, axis=1)
    ev["flags_in_interval"] = [
        int(((flags.meter_id == e.meter_id) & (flags.event_time >= e.start) &
             (flags.event_time < e.end)).sum()) for e in ev.itertuples()]
    ev["detected"] = ev["flags_in_interval"] > 0

    false_flags = flags[~flags.in_event]
    in_event_readings = int(ev.readings_in_interval.sum())
    outside = observed - in_event_readings
    meters_false = false_flags.meter_id.nunique()

    print("\nEVALUATION AGAINST anomaly_events() (labels used only here)")
    table = ev.copy()
    table["start"] = [t.strftime("%Y-%m-%d %H:%M") for t in table["start"]]
    table["end"] = [t.strftime("%H:%M") for t in table["end"]]
    print(table.to_string(index=False))

    detected = int(ev.detected.sum())
    print(f"\nDetected events: {detected} / {len(ev)}   Missed: {len(ev) - detected}")
    print(f"  spikes detected {int(ev[ev.event_type == 'demand_spike'].detected.sum())} / "
          f"{(ev.event_type == 'demand_spike').sum()}, drops detected "
          f"{int(ev[ev.event_type == 'unusual_drop'].detected.sum())} / "
          f"{(ev.event_type == 'unusual_drop').sum()}")
    print(f"Flags inside injected intervals: {int(flags.in_event.sum()):,} of "
          f"{in_event_readings:,} observed readings in those intervals")
    print(f"False flags: {len(false_flags):,} = {100 * len(false_flags) / outside:.6f} % of the "
          f"{outside:,} observed readings outside injected intervals")
    print(f"Meters with at least one false flag: {meters_false} = "
          f"{100 * meters_false / TOTAL_METERS:.2f} % of meters affected by false flags")
    if len(false_flags):
        print("False flags (first 10):")
        print(false_flags.head(10).to_string(index=False))

    # 5. Save
    flags.to_csv(OUT / "5_4_flags.csv", index=False)
    ev.to_csv(OUT / "5_4_event_evaluation.csv", index=False)
    pd.DataFrame([{"rule": f"ratio>={HIGH} or ratio<={LOW} vs median of same meter/slot/day type",
                   "flags": len(flags), "detected": detected, "missed": len(ev) - detected,
                   "false_flags": len(false_flags),
                   "false_flag_pct": 100 * len(false_flags) / outside,
                   "meters_with_false_flags": meters_false,
                   "pct_meters_affected": 100 * meters_false / TOTAL_METERS}]
                 ).to_csv(OUT / "5_4_summary.csv", index=False)

    # 6. Chart: one spike and one drop, actual vs baseline on the event day
    examples = [ev[ev.event_type == "demand_spike"].iloc[0], ev[ev.event_type == "unusual_drop"].iloc[0]]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    for ax, e in zip(axes, examples):
        day0 = e.start.replace(hour=0, minute=0)
        day = run(cur, DAY_SERIES, (int(e.meter_id), day0, day0 + timedelta(days=1)))
        day["power_kw"] = day["power_kw"].astype(float)
        day["median_kw"] = day["median_kw"].astype(float)
        ax.axvspan(e.start, e.end, color=ORANGE, alpha=0.12, lw=0)
        ax.plot(day.event_time, day.median_kw, color=MUTED, lw=1.5, ls="--", label="Baseline (median)")
        ax.plot(day.event_time, day.power_kw, color=BLUE, lw=2, label="Actual power")
        f = flags[(flags.meter_id == e.meter_id) & (flags.event_time >= day0) &
                  (flags.event_time < day0 + timedelta(days=1))]
        ax.scatter(f.event_time, f.power_kw.astype(float), s=36, color=ORANGE,
                   edgecolor="white", linewidth=1, zorder=3, label="Flagged")
        style(ax, f"{e.event_type.replace('_', ' ')}: meter {e.meter_id}, {e.start:%d %b}", "Power (kW)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=CAT))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.2f}"))
        ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG / "5_4_anomaly_examples.png", dpi=150)

    conn.close()
    print(f"\nSaved 5_4_flags.csv, 5_4_event_evaluation.csv, 5_4_summary.csv and "
          f"figures\\5_4_anomaly_examples.png  ({(datetime.now(CAT) - t0).seconds} s)")


if __name__ == "__main__":
    main()