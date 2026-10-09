"""7.4 - Browser timing of the Raw vs Aggregate Grafana dashboards.

Pauses TimescaleDB jobs, checks no writes happen, disables the browser cache,
then clicks Grafana's Refresh button: 1 warm-up + 10 measured refreshes per
dashboard (alternating Raw / Aggregate). Jobs are resumed at the end.
"""
import base64, csv, difflib, json, statistics, time
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright
from db import connect

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "grafana" / "provisioning" / "dashboards"
OUT = ROOT / "results"
GRAFANA = "http://localhost:3000"
METER = "1000000000"
QS = ("?orgId=1&from=2026-09-22T00:00:00%2B02:00&to=2026-09-29T00:00:00%2B02:00"
      f"&timezone=Africa%2FKigali&var-meter={METER}")
MODES = {"raw": "/d/energy-raw/raw", "aggregate": "/d/energy-aggregate/aggregate"}
WARMUP, RUNS, TIMEOUT_S = 1, 10, 180


def env():
    vals = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


PASSWORD = env()["GRAFANA_ADMIN_PASSWORD"]
AUTH = "Basic " + base64.b64encode(f"admin:{PASSWORD}".encode()).decode()


def norm(sql):
    return " ".join(sql.replace("${meter}", METER).replace("$meter", METER).split())


def panel_sql(mode):
    d = json.loads((DASH / f"{mode}.json").read_text(encoding="utf-8"))
    return [(p["title"], norm(p["targets"][0]["rawSql"])) for p in d["panels"] if p.get("targets")]


class Tracker:
    """Records every /api/ds/query request of one browser tab."""

    def __init__(self, page, panels):
        self.page, self.panels, self.reqs = page, panels, None
        page.on("request", self.on_request)
        page.on("response", self.on_response)
        page.on("requestfinished", self.on_finished)
        page.on("requestfailed", self.on_failed)

    def match(self, sql):
        s = norm(sql)
        best = max(self.panels, key=lambda p: difflib.SequenceMatcher(None, s, p[1]).ratio())
        return best[0] if difflib.SequenceMatcher(None, s, best[1]).ratio() > 0.9 else None

    def on_request(self, req):
        if self.reqs is None or req.method != "POST" or "/api/ds/query" not in req.url:
            return
        try:
            sql = (req.post_data_json.get("queries") or [{}])[0].get("rawSql", "")
        except Exception:
            return
        self.reqs[req] = {"panel": self.match(sql), "start": time.perf_counter(),
                          "end": None, "status": None}

    def on_response(self, resp):
        r = self.reqs.get(resp.request) if self.reqs is not None else None
        if r:
            r["status"] = resp.status

    def on_finished(self, req):
        r = self.reqs.get(req) if self.reqs is not None else None
        if r:
            r["end"] = time.perf_counter()

    def on_failed(self, req):
        r = self.reqs.get(req) if self.reqs is not None else None
        if r:
            r["end"], r["status"] = time.perf_counter(), "failed"

    def cycle(self, action):
        """Run action (load or refresh) and wait until every panel has its data."""
        self.reqs = {}
        t0 = time.perf_counter()
        action()
        want = {t for t, _ in self.panels}
        while True:
            mine = [r for r in self.reqs.values() if r["panel"]]
            done = {r["panel"] for r in mine if r["end"]}
            if done == want and all(r["end"] for r in mine):
                break
            if time.perf_counter() - t0 > TIMEOUT_S:
                raise RuntimeError(f"timeout, panels done: {sorted(done)}")
            self.page.wait_for_timeout(20)
        reqs, self.reqs = self.reqs, None
        mine = [r for r in reqs.values() if r["panel"]]
        bad = [r for r in mine if r["status"] != 200]
        if bad:
            raise RuntimeError(f"failed panel queries: {bad}")
        panel_ms = {r["panel"]: (r["end"] - r["start"]) * 1000 for r in mine}
        dash_ms = (max(r["end"] for r in mine) - t0) * 1000
        return panel_ms, dash_ms


def click_refresh(page):
    btn = page.get_by_test_id("data-testid RefreshPicker run button")
    if btn.count() == 0:
        btn = page.get_by_role("button", name="Refresh")
    btn.first.click()


def scalar(cur, sql):
    cur.execute(sql)
    return cur.fetchone()[0]


def main():
    OUT.mkdir(exist_ok=True)
    conn = connect()
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("""SELECT job_id, proc_name, coalesce(hypertable_name, '')
                   FROM timescaledb_information.jobs
                   WHERE job_id >= 1000 AND scheduled ORDER BY job_id""")
    jobs = cur.fetchall()
    paused = []
    rows = []
    meta = {"started": datetime.now().isoformat(timespec="seconds")}
    try:
        for job_id, proc, ht in jobs:
            cur.execute("SELECT alter_job(%s, scheduled => false)", (job_id,))
            paused.append(job_id)
            print(f"paused job {job_id} {proc} {ht}")
        for _ in range(300):
            if scalar(cur, "SELECT count(*) FROM timescaledb_information.job_stats "
                           "WHERE job_status = 'Running'") == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("a TimescaleDB job is still running")

        rows_before = scalar(cur, "SELECT count(*) FROM energy_readings")
        active = scalar(cur, """SELECT count(*) FROM pg_stat_activity
                                WHERE datname = current_database() AND pid <> pg_backend_pid()
                                  AND state = 'active' AND backend_type = 'client backend'""")
        print(f"energy_readings rows before: {rows_before:,}; other active sessions: {active}")

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            ctx = browser.new_context(viewport={"width": 1920, "height": 1400},
                                      extra_http_headers={"Authorization": AUTH})
            trackers = {}
            for mode, path in MODES.items():
                page = ctx.new_page()
                cdp = ctx.new_cdp_session(page)
                cdp.send("Network.enable")
                cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
                tr = Tracker(page, panel_sql(mode))
                tr.cycle(lambda pg=page, u=GRAFANA + path + QS: pg.goto(u))
                print(f"{mode}: dashboard loaded, {len(tr.panels)} panels")
                trackers[mode] = tr

            for run in range(-WARMUP + 1, RUNS + 1):          # 0 = warm-up, 1..10 measured
                for mode, tr in trackers.items():
                    tr.page.bring_to_front()
                    panel_ms, dash_ms = tr.cycle(lambda pg=tr.page: click_refresh(pg))
                    label = "warm-up" if run <= 0 else f"run {run}"
                    print(f"{label:8} {mode:9} dashboard {dash_ms:9.1f} ms")
                    if run > 0:
                        for panel, ms in panel_ms.items():
                            rows.append({"mode": mode, "run": run, "panel": panel, "ms": round(ms, 1)})
                        rows.append({"mode": mode, "run": run, "panel": "WHOLE DASHBOARD",
                                     "ms": round(dash_ms, 1)})

            for mode, tr in trackers.items():
                tr.page.screenshot(path=str(OUT / f"figures/7.4_{mode}_headless.png"), full_page=True)
            meta["chrome"] = browser.version
            browser.close()

        rows_after = scalar(cur, "SELECT count(*) FROM energy_readings")
        print(f"energy_readings rows after:  {rows_after:,} "
              f"({'unchanged' if rows_after == rows_before else 'CHANGED'})")
        meta.update(rows_before=rows_before, rows_after=rows_after, other_active_sessions=active,
                    warmup=WARMUP, runs=RUNS, viewport="1920x1400", browser_cache="disabled")
    finally:
        for job_id in paused:
            cur.execute("SELECT alter_job(%s, scheduled => true)", (job_id,))
        print(f"resumed jobs: {paused}")
        meta.update(jobs_paused_and_resumed=paused,
                    finished=datetime.now().isoformat(timespec="seconds"))
        conn.close()

    with open(OUT / "7.4_dashboard_timing_runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["mode", "run", "panel", "ms"])
        w.writeheader(); w.writerows(rows)

    panels = [t for t, _ in panel_sql("raw")] + ["WHOLE DASHBOARD"]
    summary = []
    for panel in panels:
        rec = {"panel": panel}
        for mode in MODES:
            v = [r["ms"] for r in rows if r["mode"] == mode and r["panel"] == panel]
            rec.update({f"{mode}_median": statistics.median(v), f"{mode}_min": min(v),
                        f"{mode}_max": max(v)})
        rec["speedup"] = rec["raw_median"] / rec["aggregate_median"]
        summary.append(rec)
    with open(OUT / "7.4_dashboard_timing_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=summary[0].keys())
        w.writeheader(); w.writerows(summary)
    (OUT / "7.4_dashboard_timing_meta.json").write_text(json.dumps(meta, indent=2))

    print(f"\n{RUNS} measured refreshes per dashboard, times in ms (median / min / max)\n")
    print(f"{'panel':52} {'raw median':>10} {'min':>8} {'max':>8}   {'agg median':>10} {'min':>7} {'max':>7}  {'speedup':>7}")
    for s in summary:
        print(f"{s['panel'][:52]:52} {s['raw_median']:10.1f} {s['raw_min']:8.1f} {s['raw_max']:8.1f}   "
              f"{s['aggregate_median']:10.1f} {s['aggregate_min']:7.1f} {s['aggregate_max']:7.1f}  "
              f"{s['speedup']:6.1f}x")
    print("\nwrote results\\7.4_dashboard_timing_runs.csv, _summary.csv, _meta.json, 7.4_*_headless.png")


if __name__ == "__main__":
    main()