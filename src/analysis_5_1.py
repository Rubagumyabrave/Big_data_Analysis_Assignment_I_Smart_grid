"""5.1 Demand patterns: daily and weekly network energy, the three highest 15-minute
network demand intervals, and the average daily load shape (weekday vs weekend).

  python src\\analysis_5_1.py
"""
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                      # draw to files, no window
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import ROOT, connect

OUT = ROOT / "results"
FIG = OUT / "figures"
FIG.mkdir(parents=True, exist_ok=True)
CAT = timezone(timedelta(hours=2), "CAT")

# Chart colours: one hue per meaning, quiet grid and text
BLUE, ORANGE = "#2a78d6", "#eb6834"        # weekday, weekend
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"

# ---------------- SQL ----------------
DAILY = """
SELECT (date_trunc('day', event_time, 'Africa/Kigali') AT TIME ZONE 'Africa/Kigali')::date AS day,
       sum(energy_kwh) AS energy_kwh,
       count(*)        AS readings
FROM energy_readings
GROUP BY 1
ORDER BY 1"""

WEEKLY = """
WITH daily AS (
    SELECT (date_trunc('day', event_time, 'Africa/Kigali') AT TIME ZONE 'Africa/Kigali')::date AS day,
           sum(energy_kwh) AS energy_kwh
    FROM energy_readings
    GROUP BY 1
)
SELECT DATE '2026-09-01' + 7 * ((day - DATE '2026-09-01') / 7) AS period_start,
       min(day)        AS first_day,
       max(day)        AS last_day,
       count(*)        AS days,
       sum(energy_kwh) AS energy_kwh
FROM daily
GROUP BY 1
ORDER BY 1"""

PEAKS = """
SELECT event_time,
       sum(power_kw) AS network_kw,
       count(*)      AS meters_reporting
FROM energy_readings
GROUP BY event_time
ORDER BY network_kw DESC, event_time
LIMIT 3"""

CONTEXT = """
WITH t AS (SELECT event_time, sum(power_kw) AS kw FROM energy_readings GROUP BY event_time)
SELECT avg(kw) AS avg_kw, min(kw) AS min_kw, max(kw) AS max_kw FROM t"""

PROFILE = """
WITH t AS (SELECT event_time, sum(power_kw) AS kw FROM energy_readings GROUP BY event_time)
SELECT to_char(event_time AT TIME ZONE 'Africa/Kigali', 'HH24:MI') AS time_of_day,
       CASE WHEN extract(isodow FROM event_time AT TIME ZONE 'Africa/Kigali') >= 6
            THEN 'weekend' ELSE 'weekday' END                        AS day_type,
       avg(kw)                                                        AS avg_network_kw
FROM t
GROUP BY 1, 2
ORDER BY 1, 2"""


def query(cur, sql):
    """Run SQL and return a pandas DataFrame."""
    cur.execute(sql)
    columns = [d[0] for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=columns)


def style(ax, title, ylabel):
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=12)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))


def main():
    print(f"[{datetime.now(CAT):%Y-%m-%d %H:%M:%S} CAT] 5.1 analysis on cleaned energy_readings\n")
    conn = connect()
    cur = conn.cursor()

    t0 = time.perf_counter()
    daily = query(cur, DAILY)
    weekly = query(cur, WEEKLY)
    peaks = query(cur, PEAKS)
    context = query(cur, CONTEXT)
    profile = query(cur, PROFILE)
    conn.close()
    print(f"Queries finished in {time.perf_counter() - t0:.1f} s\n")

    # ---- daily energy ----
    daily["energy_kwh"] = daily["energy_kwh"].astype(float)
    daily["weekday"] = pd.to_datetime(daily["day"]).dt.day_name().str[:3]
    daily["weekend"] = pd.to_datetime(daily["day"]).dt.dayofweek >= 5
    print("DAILY NETWORK ENERGY (CAT days)")
    print(daily.to_string(index=False, formatters={"energy_kwh": "{:,.1f}".format,
                                                   "readings": "{:,}".format}))
    wd = daily.loc[~daily.weekend, "energy_kwh"].mean()
    we = daily.loc[daily.weekend, "energy_kwh"].mean()
    print(f"\nAverage weekday: {wd:,.1f} kWh/day | average weekend day: {we:,.1f} kWh/day "
          f"({100 * (we - wd) / wd:+.1f} %)")

    # ---- weekly energy ----
    weekly["energy_kwh"] = weekly["energy_kwh"].astype(float)
    print("\nSEVEN-DAY PERIODS")
    print(weekly.to_string(index=False, formatters={"energy_kwh": "{:,.1f}".format}))
    first, last = weekly["energy_kwh"].iloc[0], weekly["energy_kwh"].iloc[-1]
    print(f"Change from period 1 to period 4: {100 * (last - first) / first:+.1f} %")

    # ---- peak demand ----
    peaks["network_kw"] = peaks["network_kw"].astype(float)
    peaks["weekday"] = [t.strftime("%a") for t in peaks["event_time"]]
    peaks["event_time"] = [t.strftime("%Y-%m-%d %H:%M CAT") for t in peaks["event_time"]]
    print("\nTHREE HIGHEST 15-MINUTE NETWORK DEMAND INTERVALS (sum of power_kw)")
    print(peaks.to_string(index=False, formatters={"network_kw": "{:,.1f}".format}))
    c = context.iloc[0].astype(float)
    print(f"For comparison: average interval {c.avg_kw:,.1f} kW, lowest {c.min_kw:,.1f} kW, "
          f"peak/average = {c.max_kw / c.avg_kw:.2f}")

    # ---- save tables ----
    daily.to_csv(OUT / "5_1_daily_energy.csv", index=False)
    weekly.to_csv(OUT / "5_1_weekly_energy.csv", index=False)
    peaks.to_csv(OUT / "5_1_peak_intervals.csv", index=False)
    profile.to_csv(OUT / "5_1_daily_profile.csv", index=False)

    # ---- chart 1: daily energy ----
    fig, ax = plt.subplots(figsize=(12, 4.8))
    colors = [ORANGE if w else BLUE for w in daily["weekend"]]
    ax.bar(range(len(daily)), daily["energy_kwh"], width=0.75, color=colors,
           edgecolor="white", linewidth=1)
    ax.set_xticks(range(len(daily)))
    ax.set_xticklabels([f"{d.day}\n{w}" for d, w in zip(daily["day"], daily["weekday"])], fontsize=8)
    style(ax, "Total network energy per CAT day, 1-28 September 2026", "Energy (kWh)")
    ax.legend(handles=[Patch(color=BLUE, label="Weekday"), Patch(color=ORANGE, label="Weekend")],
              frameon=False, loc="upper left", ncols=2)
    fig.tight_layout()
    fig.savefig(FIG / "5_1_daily_energy.png", dpi=150)

    # ---- chart 2: seven-day periods ----
    fig, ax = plt.subplots(figsize=(7, 4.5))
    labels = [f"{a.day}-{b.day} Sep" for a, b in zip(weekly["first_day"], weekly["last_day"])]
    bars = ax.bar(labels, weekly["energy_kwh"], width=0.6, color=BLUE, edgecolor="white", linewidth=1)
    for bar, value in zip(bars, weekly["energy_kwh"]):
        ax.text(bar.get_x() + bar.get_width() / 2, value, f"{value:,.0f}",
                ha="center", va="bottom", fontsize=9, color=INK)
    style(ax, "Network energy per seven-day period", "Energy (kWh)")
    fig.tight_layout()
    fig.savefig(FIG / "5_1_weekly_energy.png", dpi=150)

    # ---- chart 3: average daily load shape ----
    pivot = profile.pivot(index="time_of_day", columns="day_type", values="avg_network_kw").astype(float)
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(range(len(pivot)), pivot["weekday"], color=BLUE, linewidth=2, label="Weekday")
    ax.plot(range(len(pivot)), pivot["weekend"], color=ORANGE, linewidth=2, label="Weekend")
    ax.set_xticks(range(0, len(pivot), 8))
    ax.set_xticklabels(pivot.index[::8])
    style(ax, "Average network demand by time of day (CAT)", "Power (kW)")
    ax.set_xlabel("Time of day (interval start)", color=MUTED)
    ax.legend(frameon=False, loc="upper left", ncols=2)
    fig.tight_layout()
    fig.savefig(FIG / "5_1_daily_profile.png", dpi=150)

    print(f"\nSaved CSVs in results\\ and charts in results\\figures\\: "
          f"5_1_daily_energy.png, 5_1_weekly_energy.png, 5_1_daily_profile.png")


if __name__ == "__main__":
    main()