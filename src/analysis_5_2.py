"""5.2 Compare energy by region and by customer type, normalised by registered meter count.

  python src\\analysis_5_2.py
"""
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect
from analysis_5_1 import BLUE, CAT, FIG, OUT, query, style

BY_REGION = r"""
WITH energy AS (
    SELECT m.region, sum(r.energy_kwh) AS energy_kwh, count(*) AS readings
    FROM energy_readings r
    JOIN meters m USING (meter_id)
    GROUP BY m.region
), registered AS (
    SELECT region, count(*) AS registered_meters FROM meters GROUP BY region
)
SELECT g.region, g.registered_meters, e.readings,
       e.energy_kwh,
       e.energy_kwh / g.registered_meters                 AS kwh_per_meter,
       100 * e.energy_kwh / sum(e.energy_kwh) OVER ()     AS pct_of_energy
FROM registered g
JOIN energy e USING (region)
ORDER BY substring(g.region FROM '[0-9]+')::int"""

BY_TYPE = """
WITH energy AS (
    SELECT m.customer_type, sum(r.energy_kwh) AS energy_kwh, count(*) AS readings
    FROM energy_readings r
    JOIN meters m USING (meter_id)
    GROUP BY m.customer_type
), registered AS (
    SELECT customer_type, count(*) AS registered_meters FROM meters GROUP BY customer_type
)
SELECT g.customer_type, g.registered_meters,
       100.0 * g.registered_meters / sum(g.registered_meters) OVER () AS pct_of_meters,
       e.readings,
       e.energy_kwh,
       e.energy_kwh / g.registered_meters                             AS kwh_per_meter,
       100 * e.energy_kwh / sum(e.energy_kwh) OVER ()                 AS pct_of_energy
FROM registered g
JOIN energy e USING (customer_type)
ORDER BY kwh_per_meter DESC"""

# Region x customer type: meter mix and energy per meter within each type
MIX = r"""
WITH energy AS (
    SELECT m.region, m.customer_type, sum(r.energy_kwh) AS energy_kwh
    FROM energy_readings r
    JOIN meters m USING (meter_id)
    GROUP BY m.region, m.customer_type
), registered AS (
    SELECT region, customer_type, count(*) AS meters FROM meters GROUP BY region, customer_type
)
SELECT g.region, g.customer_type, g.meters, e.energy_kwh / g.meters AS kwh_per_meter
FROM registered g
JOIN energy e USING (region, customer_type)
ORDER BY substring(g.region FROM '[0-9]+')::int, g.customer_type"""


def main():
    print(f"[{datetime.now(CAT):%Y-%m-%d %H:%M:%S} CAT] 5.2 regions and customer types "
          "(28 days, cleaned energy_readings JOIN meters)\n")
    conn = connect()
    cur = conn.cursor()
    region = query(cur, BY_REGION)
    ctype = query(cur, BY_TYPE)
    mix = query(cur, MIX)
    conn.close()

    for df in (region, ctype, mix):
        for col in ("energy_kwh", "kwh_per_meter", "pct_of_energy", "pct_of_meters"):
            if col in df:
                df[col] = df[col].astype(float)

    fmt = {"energy_kwh": "{:,.1f}".format, "kwh_per_meter": "{:,.1f}".format,
           "pct_of_energy": "{:.2f}".format, "pct_of_meters": "{:.2f}".format,
           "readings": "{:,}".format}
    print("BY REGION")
    print(region.to_string(index=False, formatters=fmt))
    spread = region.kwh_per_meter.max() / region.kwh_per_meter.min()
    print(f"Highest / lowest kWh per meter: {spread:.2f}x\n")

    print("BY CUSTOMER TYPE")
    print(ctype.to_string(index=False, formatters=fmt))
    print()

    # Meter mix per region and energy per meter within each customer type
    counts = mix.pivot(index="region", columns="customer_type", values="meters")
    per_meter = mix.pivot(index="region", columns="customer_type", values="kwh_per_meter")
    order = sorted(counts.index, key=lambda r: int(r.split()[-1]))
    counts, per_meter = counts.loc[order], per_meter.loc[order]
    counts["industrial_share_%"] = 100 * counts["industrial"] / counts.sum(axis=1)
    print("METER MIX PER REGION (registered meters)")
    print(counts.to_string(formatters={"industrial_share_%": "{:.1f}".format}))
    print("\nkWh PER METER WITHIN EACH CUSTOMER TYPE")
    print(per_meter.to_string(float_format="{:,.1f}".format))
    print("\nSpread within each type (highest / lowest region):")
    for t in per_meter.columns:
        print(f"  {t:<12} {per_meter[t].max() / per_meter[t].min():.2f}x")

    # Correlation: does the industrial share explain the regional differences?
    joined = region.set_index("region").loc[order]
    r_value = joined["kwh_per_meter"].corr(counts["industrial_share_%"])
    print(f"\nCorrelation between region kWh/meter and industrial share of meters: r = {r_value:.2f}")

    region.to_csv(OUT / "5_2_by_region.csv", index=False)
    ctype.to_csv(OUT / "5_2_by_customer_type.csv", index=False)
    mix.to_csv(OUT / "5_2_region_customer_mix.csv", index=False)

    # Charts: energy per meter by region and by customer type
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.bar([r.replace("Region ", "R") for r in joined.index], joined["kwh_per_meter"],
           width=0.6, color=BLUE, edgecolor="white", linewidth=1)
    style(ax, "Energy per registered meter by region, 1-28 September", "kWh per meter")
    fig.tight_layout()
    fig.savefig(FIG / "5_2_region_per_meter.png", dpi=150)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    bars = ax.bar(ctype["customer_type"], ctype["kwh_per_meter"], width=0.55,
                  color=BLUE, edgecolor="white", linewidth=1)
    for bar, v in zip(bars, ctype["kwh_per_meter"]):
        ax.text(bar.get_x() + bar.get_width() / 2, v, f"{v:,.0f}",
                ha="center", va="bottom", fontsize=9)
    style(ax, "Energy per registered meter by customer type", "kWh per meter")
    fig.tight_layout()
    fig.savefig(FIG / "5_2_type_per_meter.png", dpi=150)
    print("\nSaved CSVs and charts 5_2_region_per_meter.png, 5_2_type_per_meter.png")


if __name__ == "__main__":
    main()