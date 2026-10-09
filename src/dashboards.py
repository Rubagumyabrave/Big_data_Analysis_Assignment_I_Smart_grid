"""Section 7: one source of truth for the Raw and Aggregate Grafana dashboards.

  python src\\dashboards.py   -> writes grafana/provisioning/dashboards/raw.json and aggregate.json

verify_dashboards.py (7.3) imports PANELS, so the check runs exactly the dashboard queries.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH_DIR = ROOT / "grafana" / "provisioning" / "dashboards"
DATASOURCE = {"type": "grafana-postgresql-datasource", "uid": "smartgrid"}

# The selected range snapped to whole CAT days: [CAT midnight of "from", CAT midnight after "to")
FROM_DAY = "time_bucket('1 day', $__timeFrom()::timestamptz, 'Africa/Kigali')"
TO_DAY = ("(time_bucket('1 day', $__timeTo()::timestamptz - INTERVAL '1 microsecond', "
          "'Africa/Kigali') + INTERVAL '1 day')")
DAYS = f"(extract(epoch FROM {TO_DAY} - {FROM_DAY}) / 86400)"
RAW_RANGE = f"r.event_time >= {FROM_DAY} AND r.event_time < {TO_DAY}"
AGG_RANGE = f"v.bucket >= {FROM_DAY} AND v.bucket < {TO_DAY}"
PERIOD_ORIGIN = "TIMESTAMPTZ '2026-09-01 00:00+02'"          # seven-day periods start 1 Sep (5.1)
REGION_ORDER = "substring(region FROM 8)::int"

PANELS = [
    {   # 1. Hourly regional energy
        "key": "hourly_regional_energy", "title": "Hourly regional energy (kWh)",
        "type": "timeseries", "format": "time_series", "unit": "kwatth",
        "keys": ["time", "metric"], "display_name": "${__field.labels.metric}",
        "raw": f"""
SELECT time_bucket('1 hour', r.event_time, 'Africa/Kigali') AS time, m.region AS metric,
       sum(r.energy_kwh) AS energy_kwh, count(*) AS reading_count
FROM energy_readings r JOIN meters m ON m.meter_id = r.meter_id
WHERE {RAW_RANGE}
GROUP BY 1, 2 ORDER BY 1, 2""",
        "aggregate": f"""
SELECT v.bucket AS time, v.region AS metric,
       sum(v.energy_kwh) AS energy_kwh, sum(v.reading_count) AS reading_count
FROM energy_hourly_region v
WHERE {AGG_RANGE}
GROUP BY 1, 2 ORDER BY 1, 2""",
    },
    {   # 2. Daily network energy
        "key": "daily_network_energy", "title": "Daily network energy (kWh)",
        "type": "timeseries", "format": "time_series", "unit": "kwatth", "bars": True,
        "keys": ["time"], "display_name": "Energy (kWh)",
        "raw": f"""
SELECT time_bucket('1 day', r.event_time, 'Africa/Kigali') AS time,
       sum(r.energy_kwh) AS energy_kwh, count(*) AS reading_count
FROM energy_readings r
WHERE {RAW_RANGE}
GROUP BY 1 ORDER BY 1""",
        "aggregate": f"""
SELECT time_bucket('1 day', v.bucket, 'Africa/Kigali') AS time,
       sum(v.energy_kwh) AS energy_kwh, sum(v.reading_count) AS reading_count
FROM energy_15min_region v
WHERE {AGG_RANGE}
GROUP BY 1 ORDER BY 1""",
    },
    {   # 3. Seven-day periods from 1 September
        "key": "seven_day_network_energy",
        "title": "Network energy per seven-day period from 1 Sep (kWh)",
        "type": "barchart", "format": "table", "unit": "kwatth",
        "display_name": "Energy (kWh)", "keys": ["period"],
        "raw": f"""
SELECT to_char(time_bucket('7 days', r.event_time, {PERIOD_ORIGIN}), 'DD Mon') AS period,
       sum(r.energy_kwh) AS energy_kwh, count(*) AS reading_count
FROM energy_readings r
WHERE {RAW_RANGE}
GROUP BY time_bucket('7 days', r.event_time, {PERIOD_ORIGIN})
ORDER BY time_bucket('7 days', r.event_time, {PERIOD_ORIGIN})""",
        "aggregate": f"""
SELECT to_char(time_bucket('7 days', v.bucket, {PERIOD_ORIGIN}), 'DD Mon') AS period,
       sum(v.energy_kwh) AS energy_kwh, sum(v.reading_count) AS reading_count
FROM energy_15min_region v
WHERE {AGG_RANGE}
GROUP BY time_bucket('7 days', v.bucket, {PERIOD_ORIGIN})
ORDER BY time_bucket('7 days', v.bucket, {PERIOD_ORIGIN})""",
    },
    {   # 4. Daily energy for the selected meter
        "key": "meter_daily_energy", "title": "Daily energy for meter $meter (kWh)",
        "type": "timeseries", "format": "time_series", "unit": "kwatth", "bars": True,
        "keys": ["time"], "display_name": "Energy (kWh)",
        "raw": f"""
SELECT time_bucket('1 day', r.event_time, 'Africa/Kigali') AS time,
       sum(r.energy_kwh) AS energy_kwh, count(*) AS reading_count
FROM energy_readings r
WHERE r.meter_id = $meter AND {RAW_RANGE}
GROUP BY 1 ORDER BY 1""",
        "aggregate": f"""
SELECT v.bucket AS time, sum(v.energy_kwh) AS energy_kwh, sum(v.reading_count) AS reading_count
FROM energy_daily_meter v
WHERE v.meter_id = $meter AND {AGG_RANGE}
GROUP BY 1 ORDER BY 1""",
    },
    {   # 5. Completeness by region (5.3 definition)
        "key": "completeness_by_region", "title": "Completeness by region (%)",
        "type": "bargauge", "format": "table", "unit": "percent",
        "display_name": "${__data.fields.region}", "keys": ["region"],
        "raw": f"""
WITH registered AS (SELECT region, count(*) AS meters FROM meters GROUP BY region),
     observed AS (
        SELECT m.region, count(*) AS reading_count
        FROM energy_readings r JOIN meters m ON m.meter_id = r.meter_id
        WHERE {RAW_RANGE}
        GROUP BY m.region)
SELECT g.region, coalesce(o.reading_count, 0) AS reading_count,
       g.meters * 96 * {DAYS} AS planned_readings,
       100.0 * coalesce(o.reading_count, 0) / (g.meters * 96 * {DAYS}) AS completeness_pct
FROM registered g LEFT JOIN observed o USING (region)
ORDER BY {REGION_ORDER}""",
        "aggregate": f"""
WITH registered AS (SELECT region, count(*) AS meters FROM meters GROUP BY region),
     observed AS (
        SELECT v.region, sum(v.reading_count) AS reading_count
        FROM energy_15min_region v
        WHERE {AGG_RANGE}
        GROUP BY v.region)
SELECT g.region, coalesce(o.reading_count, 0) AS reading_count,
       g.meters * 96 * {DAYS} AS planned_readings,
       100.0 * coalesce(o.reading_count, 0) / (g.meters * 96 * {DAYS}) AS completeness_pct
FROM registered g LEFT JOIN observed o USING (region)
ORDER BY {REGION_ORDER}""",
    },
]

# Same layout in both dashboards: (x, y, width, height) on Grafana's 24-column grid
GRID = [(0, 0, 24, 9), (0, 9, 12, 8), (12, 9, 12, 8), (0, 17, 12, 8), (12, 17, 12, 8)]


def field_config(panel):
    custom = {}
    if panel["type"] == "timeseries":
        custom = {"drawStyle": "bars" if panel.get("bars") else "line",
                  "fillOpacity": 60 if panel.get("bars") else 10,
                  "lineWidth": 1, "showPoints": "never"}
    defaults = {"unit": panel["unit"], "decimals": 2 if panel["unit"] == "percent" else 1,
                "custom": custom, "displayName": panel.get("display_name", "")}
    if panel["unit"] == "percent":
        defaults.update(min=95, max=100)
    return {"defaults": defaults, "overrides": []}


def panel_json(panel, mode, idx):
    x, y, w, h = GRID[idx]
    p = {
        "id": idx + 1, "title": panel["title"], "type": panel["type"],
        "datasource": DATASOURCE, "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"refId": "A", "datasource": DATASOURCE, "editorMode": "code",
                     "format": panel["format"], "rawQuery": True, "rawSql": panel[mode].strip()}],
        "fieldConfig": field_config(panel),
        # reading_count / planned_readings stay in the query result (for the 7.3 check)
        # but are hidden from the chart
        "transformations": [{"id": "filterFieldsByName", "options": {"include": {
            "pattern": "^(Time|time|period|region|completeness_pct|energy_kwh.*)$"}}}],
        "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                    "tooltip": {"mode": "multi"}},
    }
    if panel["type"] == "bargauge":
        p["options"] = {"orientation": "horizontal", "displayMode": "basic",
                        "reduceOptions": {"values": True, "calcs": [], "fields": ""},
                        "showUnfilled": True}
    if panel["type"] == "barchart":
        p["options"] = {"xField": "period", "orientation": "vertical", "showValue": "always",
                        "legend": {"showLegend": False, "displayMode": "list", "placement": "bottom"}}
    return p


def dashboard_json(mode):
    name = "Raw" if mode == "raw" else "Aggregate"
    return {
        "uid": f"energy-{mode}", "title": name, "timezone": "Africa/Kigali",
        "editable": True, "refresh": "", "schemaVersion": 39, "tags": ["assignment1"],
        "time": {"from": "2026-09-22T00:00:00+02:00", "to": "2026-09-29T00:00:00+02:00"},
        "timepicker": {"refresh_intervals": []},
        "templating": {"list": [{
            "name": "meter", "label": "Meter", "type": "query", "datasource": DATASOURCE,
            "query": "SELECT meter_id::text FROM meters ORDER BY meter_id",
            "definition": "SELECT meter_id::text FROM meters ORDER BY meter_id",
            "refresh": 1, "current": {"text": "1000000000", "value": "1000000000"},
            "includeAll": False, "multi": False}]},
        "panels": [panel_json(p, mode, i) for i, p in enumerate(PANELS)],
    }


def main():
    DASH_DIR.mkdir(parents=True, exist_ok=True)
    (DASH_DIR / "dashboards.yaml").write_text(
        "apiVersion: 1\nproviders:\n  - name: assignment1\n    type: file\n"
        "    allowUiUpdates: true\n    options:\n"
        "      path: /etc/grafana/provisioning/dashboards\n", encoding="utf-8")
    for mode in ("raw", "aggregate"):
        out = DASH_DIR / f"{mode}.json"
        out.write_text(json.dumps(dashboard_json(mode), indent=2), encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()