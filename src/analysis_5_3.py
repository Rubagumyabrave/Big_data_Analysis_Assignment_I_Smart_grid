"""5.3 Reporting quality: completeness (network and per region) and the 21 September
daily total using only on-time arrivals vs all arrivals.

  python src\\analysis_5_3.py
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect
from analysis_5_1 import CAT, OUT, query

# Completeness per region and for the whole network (cleaned table: each row is a unique pair)
COMPLETENESS = r"""
WITH observed AS (
    SELECT m.region, count(*) AS observed_pairs
    FROM energy_readings r
    JOIN meters m USING (meter_id)
    GROUP BY m.region
), registered AS (
    SELECT region, count(*) AS registered_meters FROM meters GROUP BY region
), per_region AS (
    SELECT g.region, g.registered_meters,
           g.registered_meters * 28 * 96 AS planned_pairs,
           o.observed_pairs
    FROM registered g
    JOIN observed o USING (region)
)
SELECT * FROM (
    SELECT region, registered_meters, planned_pairs, observed_pairs,
           planned_pairs - observed_pairs                  AS missing_pairs,
           100.0 * observed_pairs / planned_pairs          AS completeness_pct
    FROM per_region
    UNION ALL
    SELECT 'NETWORK', sum(registered_meters), sum(planned_pairs), sum(observed_pairs),
           sum(planned_pairs) - sum(observed_pairs),
           100.0 * sum(observed_pairs) / sum(planned_pairs)
    FROM per_region
) t
ORDER BY region = 'NETWORK', substring(region FROM '[0-9]+')::int"""

# 21 September: on-time (arrived by 22 Sep 00:00) vs all arrivals
SEPT21 = """
SELECT count(*) FILTER (WHERE received_time <= '2026-09-22 00:00:00+02')           AS readings_by_midnight,
       count(*)                                                                    AS readings_final,
       sum(energy_kwh) FILTER (WHERE received_time <= '2026-09-22 00:00:00+02')    AS energy_by_midnight_kwh,
       sum(energy_kwh)                                                             AS energy_final_kwh,
       4000 * 96                                                                   AS planned_readings,
       min(event_time) FILTER (WHERE received_time > '2026-09-22 00:00:00+02')     AS first_late_event,
       max(received_time)                                                          AS last_arrival
FROM energy_readings
WHERE event_time >= '2026-09-21 00:00:00+02'
  AND event_time <  '2026-09-22 00:00:00+02'"""

# Late 21 September readings grouped by the hour in which they arrived
LATE_DETAIL = """
SELECT date_trunc('hour', received_time, 'Africa/Kigali') AS arrival_hour,
       count(*)                                          AS readings,
       sum(energy_kwh)                                   AS energy_kwh
FROM energy_readings
WHERE event_time >= '2026-09-21 00:00:00+02'
  AND event_time <  '2026-09-22 00:00:00+02'
  AND received_time > '2026-09-22 00:00:00+02'
GROUP BY 1
ORDER BY 1"""


def main():
    print(f"[{datetime.now(CAT):%Y-%m-%d %H:%M:%S} CAT] 5.3 reporting quality (cleaned energy_readings)\n")
    conn = connect()
    cur = conn.cursor()
    comp = query(cur, COMPLETENESS)
    s = query(cur, SEPT21).iloc[0]
    late = query(cur, LATE_DETAIL)
    conn.close()

    # ---- completeness ----
    comp["completeness_pct"] = comp["completeness_pct"].astype(float)
    print("COMPLETENESS = 100 x observed unique pairs / (registered meters x 28 days x 96)")
    print(comp.to_string(index=False, formatters={
        "planned_pairs": "{:,}".format, "observed_pairs": "{:,}".format,
        "missing_pairs": "{:,}".format, "completeness_pct": "{:.4f}".format}))
    regions = comp[comp.region != "NETWORK"]
    print(f"Range across regions: {regions.completeness_pct.min():.4f} % to "
          f"{regions.completeness_pct.max():.4f} % "
          f"(spread {regions.completeness_pct.max() - regions.completeness_pct.min():.4f} points)\n")

    # ---- 21 September: by midnight vs final ----
    on_time = float(s["energy_by_midnight_kwh"])
    final = float(s["energy_final_kwh"])
    diff = final - on_time
    n_on_time = int(s["readings_by_midnight"])
    n_final = int(s["readings_final"])
    planned = int(s["planned_readings"])
    print("21 SEPTEMBER DAILY ENERGY (event_time on 21 Sep CAT)")
    print(f"  Readings arrived by 22 Sep 00:00 : {n_on_time:>9,}   energy {on_time:>12,.3f} kWh")
    print(f"  All readings (final)             : {n_final:>9,}   energy {final:>12,.3f} kWh")
    print(f"  Difference (late arrivals)       : {n_final - n_on_time:>9,}   energy {diff:>12,.3f} kWh"
          f" = {100 * diff / final:.4f} % of the final total")
    print(f"  Planned readings for the day     : {planned:>9,}   never received: "
          f"{planned - n_final:,} ({100 * (planned - n_final) / planned:.2f} %)")
    print(f"  Earliest event_time among late readings: {s['first_late_event']:%Y-%m-%d %H:%M} CAT")
    print(f"  Last arrival for 21 Sep readings       : {s['last_arrival']:%Y-%m-%d %H:%M} CAT\n")

    # ---- when the late readings arrived ----
    late["energy_kwh"] = late["energy_kwh"].astype(float)
    late["arrival_hour"] = [t.strftime("%Y-%m-%d %H:00") for t in late["arrival_hour"]]
    print("LATE 21 SEP READINGS BY ARRIVAL HOUR (CAT)")
    print(late.to_string(index=False, formatters={"energy_kwh": "{:,.3f}".format}))

    # ---- save ----
    comp.to_csv(OUT / "5_3_completeness.csv", index=False)
    late.to_csv(OUT / "5_3_sept21_late_arrivals.csv", index=False)
    (OUT / "5_3_sept21_totals.txt").write_text(
        f"readings_by_midnight={n_on_time}\nreadings_final={n_final}\n"
        f"on_time_kwh={on_time:.3f}\nfinal_kwh={final:.3f}\ndifference_kwh={diff:.3f}\n"
        f"difference_pct_of_final={100 * diff / final:.4f}\n")
    print("\nSaved results\\5_3_completeness.csv, 5_3_sept21_late_arrivals.csv, 5_3_sept21_totals.txt")


if __name__ == "__main__":
    main()