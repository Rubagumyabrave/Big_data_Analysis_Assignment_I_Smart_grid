"""7.3 - Verify Raw and Aggregate dashboards return the same results.

Sends every panel query through Grafana's /api/ds/query (the same path the
browser uses), for 22-29 Sep 2026 CAT and meter 1000000000, then compares
raw vs aggregate value by value.
"""
import base64, csv, json, time, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "grafana" / "provisioning" / "dashboards"
OUT = ROOT / "results"
GRAFANA = "http://localhost:3000"
METER = "1000000000"
CAT = timezone(timedelta(hours=2))
FROM = datetime(2026, 9, 22, tzinfo=CAT)
TO = datetime(2026, 9, 29, tzinfo=CAT)
TOL_KWH, TOL_PCT = 0.001, 0.000001


def env():
    vals = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


PASSWORD = env()["GRAFANA_ADMIN_PASSWORD"]
AUTH = "Basic " + base64.b64encode(f"admin:{PASSWORD}".encode()).decode()


def ds_query(target):
    sql = target["rawSql"].replace("${meter}", METER).replace("$meter", METER)
    body = {
        "from": str(int(FROM.timestamp() * 1000)),
        "to": str(int(TO.timestamp() * 1000)),
        "queries": [{
            "refId": "A",
            "datasource": target.get("datasource", {"uid": "smartgrid"}),
            "rawSql": sql,
            "rawQuery": True,
            "editorMode": "code",
            "format": target.get("format", "table"),
        }],
    }
    req = urllib.request.Request(
        f"{GRAFANA}/api/ds/query", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": AUTH})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.load(r)
    ms = (time.perf_counter() - t0) * 1000
    result = res["results"]["A"]
    if result.get("error"):
        raise RuntimeError(result["error"])
    return result.get("frames", []), ms


def flatten(frames):
    """Turn Grafana frames into {(key...): value} for every numeric cell."""
    cells, rows = {}, 0
    for f in frames:
        fields = f["schema"]["fields"]
        values = f["data"]["values"]
        n = len(values[0]) if values else 0
        rows += n
        key_idx = [i for i, fd in enumerate(fields) if fd.get("type") in ("time", "string")]
        num_idx = [i for i, fd in enumerate(fields) if fd.get("type") == "number"]
        for r in range(n):
            key = tuple(values[i][r] for i in key_idx)
            for i in num_idx:
                fd = fields[i]
                labels = tuple(sorted((fd.get("labels") or {}).items()))
                cells[key + (fd["name"], labels)] = values[i][r]
    return cells, rows


def panels(name):
    d = json.loads((DASH / f"{name}.json").read_text(encoding="utf-8"))
    return [p for p in d["panels"] if p.get("targets")]


def main():
    raw_panels, agg_panels = panels("raw"), panels("aggregate")
    assert len(raw_panels) == len(agg_panels), "panel count differs"
    report = []
    for rp, ap in zip(raw_panels, agg_panels):
        title = rp["title"]
        tol = TOL_PCT if "%" in title else TOL_KWH
        raw_cells, raw_rows = flatten(ds_query(rp["targets"][0])[0])
        agg_cells, agg_rows = flatten(ds_query(ap["targets"][0])[0])
        keys = set(raw_cells) | set(agg_cells)
        missing = sum(1 for k in keys if k not in raw_cells or k not in agg_cells)
        diffs = [abs((raw_cells[k] or 0) - (agg_cells[k] or 0))
                 for k in keys if k in raw_cells and k in agg_cells]
        max_diff = max(diffs) if diffs else 0.0
        ok = raw_rows == agg_rows and missing == 0 and max_diff <= tol
        report.append({"panel": title, "raw_rows": raw_rows, "agg_rows": agg_rows,
                       "values_compared": len(diffs), "unmatched_keys": missing,
                       "max_abs_diff": max_diff, "tolerance": tol,
                       "result": "PASS" if ok else "FAIL"})

    print(f"Range {FROM:%Y-%m-%d %H:%M} to {TO:%Y-%m-%d %H:%M} CAT, meter {METER}\n")
    print(f"{'panel':52} {'raw':>5} {'agg':>5} {'values':>7} {'unmatch':>7} {'max diff':>12}  result")
    for r in report:
        print(f"{r['panel'][:52]:52} {r['raw_rows']:>5} {r['agg_rows']:>5} "
              f"{r['values_compared']:>7} {r['unmatched_keys']:>7} {r['max_abs_diff']:>12.9f}  {r['result']}")
    overall = all(r["result"] == "PASS" for r in report)
    print(f"\nOVERALL: {'PASS' if overall else 'FAIL'}")

    OUT.mkdir(exist_ok=True)
    with open(OUT / "7.3_dashboard_verification.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=report[0].keys())
        w.writeheader(); w.writerows(report)
    print("wrote results\\7.3_dashboard_verification.csv")


if __name__ == "__main__":
    main()