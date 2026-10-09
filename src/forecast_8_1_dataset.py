"""8.1 - Hourly regional dataset, chronological split, origin-safe features.

One row per region and CAT hour (1-28 Sep 2026) summing energy_kwh from the
cleaned energy_readings. Forecast origin = 00:00 CAT of the target day; every
feature uses only hours that ended at or before that origin.
Saves data/forecast_dataset.pkl (used by 8.2-8.4) and results/8_1_*.csv/.txt.
"""
from datetime import datetime
from pathlib import Path
import pandas as pd
from db import connect

ROOT = Path(__file__).resolve().parents[1]
OUT, DATA = ROOT / "results", ROOT / "data"
TZ = "Africa/Kigali"
LOG = []

SQL = """
SELECT time_bucket('1 hour', r.event_time, 'Africa/Kigali') AS hour_start,
       m.region, sum(r.energy_kwh) AS energy_kwh, count(*) AS readings
FROM energy_readings r JOIN meters m ON m.meter_id = r.meter_id
WHERE r.event_time >= '2026-09-01 00:00:00+02' AND r.event_time < '2026-09-29 00:00:00+02'
GROUP BY 1, 2
"""
LAGS = [24, 48, 168]                     # lag features kept as predictors
SPLITS = [("train", "2026-09-01", "2026-09-14"),
          ("validation", "2026-09-15", "2026-09-21"),
          ("test", "2026-09-22", "2026-09-28")]


def log(text=""):
    print(text)
    LOG.append(str(text))


def region_key(r):
    return int(r.split()[-1])


def main():
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    log(f"8.1 run started {datetime.now():%Y-%m-%d %H:%M:%S} CAT")

    # ---------- 1. hourly regional totals from cleaned readings ----------
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SQL)
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["hour_start", "region", "energy_kwh", "readings"])
    df["hour_start"] = pd.to_datetime(df["hour_start"], utc=True).dt.tz_convert(TZ)
    df["energy_kwh"] = df["energy_kwh"].astype(float)

    regions = sorted(df["region"].unique(), key=region_key)
    hours = pd.date_range("2026-09-01", "2026-09-29", freq="h", inclusive="left", tz=TZ)
    grid = pd.MultiIndex.from_product([regions, hours], names=["region", "hour_start"]).to_frame(index=False)
    df = grid.merge(df, on=["region", "hour_start"], how="left")
    absent = int(df["energy_kwh"].isna().sum())

    log("\n=== Dataset ===")
    log(f"Region-hour rows from SQL: {len(rows):,}; complete grid: {len(grid):,} "
        f"({len(regions)} regions x {len(hours)} hours); absent region-hours: {absent}")
    r = df["readings"]
    log(f"Readings per region-hour: min={r.min():.0f}, median={r.median():.0f}, max={r.max():.0f} "
        f"(planned 400 meters x 4 = 1,600)")
    log(f"Total energy: {df['energy_kwh'].sum():,.6f} kWh (cleaned table total 3,853,704.346816)")
    log("Handling: absent hours would stay NaN (never filled with 0); targets keep observed totals; "
        "rows with any missing predictor are excluded, no imputation.")

    # ---------- 2. features, origin = 00:00 of the target day ----------
    df["origin"] = df["hour_start"].dt.normalize()
    df["hour"] = df["hour_start"].dt.hour
    df["dow"] = df["hour_start"].dt.dayofweek          # 0 = Monday
    s = df.set_index(["region", "hour_start"])["energy_kwh"]

    def lag(k):
        idx = pd.MultiIndex.from_arrays([df["region"], df["hour_start"] - pd.Timedelta(hours=k)])
        return s.reindex(idx).to_numpy()

    week = pd.DataFrame({k: lag(k) for k in range(24, 169, 24)})
    for k in LAGS:
        df[f"lag_{k}h"] = week[k].to_numpy()
    df["prev_week_same_hour_mean"] = week.mean(axis=1, skipna=False).to_numpy()

    day = df.assign(day=df["origin"]).groupby(["region", "day"])["energy_kwh"].agg(["mean", "count"])
    day.loc[day["count"] < 24, "mean"] = float("nan")
    idx = pd.MultiIndex.from_arrays([df["region"], df["origin"] - pd.Timedelta(days=1)])
    df["prev_day_mean"] = day["mean"].reindex(idx).to_numpy()

    features = [f"lag_{k}h" for k in LAGS] + ["prev_day_mean", "prev_week_same_hour_mean"]
    calendar = ["hour", "dow", "region"]

    # ---------- 3. chronological split by target timestamp ----------
    df["split"] = None
    for name, first, last in SPLITS:
        d = df["hour_start"].dt.date.astype(str)
        df.loc[(d >= first) & (d <= last), "split"] = name
    df["complete"] = df[features].notna().all(axis=1)

    # ---------- 4. feature table ----------
    windows = {"lag_24h": "lag 24 h", "lag_48h": "lag 48 h", "lag_168h": "lag 168 h",
               "prev_day_mean": "window 24 h ending at origin",
               "prev_week_same_hour_mean": "window 168 h (7 same-hour values)",
               "hour": "calendar, no lag", "dow": "calendar, no lag", "region": "categorical, no lag"}
    ftab = pd.DataFrame([{"feature": f, "lag_or_window": windows[f],
                          "earliest_usable_target": df.loc[df[f].notna(), "hour_start"].min()}
                         for f in features + calendar])
    log("\n=== Features (forecast origin = 00:00 CAT of the target day) ===")
    log(ftab.to_string(index=False))

    # ---------- 5. leakage checks: every source hour ends at or before its origin ----------
    one_h = pd.Timedelta(hours=1)
    checks = {f"lag_{k}h": ((df["hour_start"] - pd.Timedelta(hours=k) + one_h) <= df["origin"])
              for k in LAGS}
    checks["prev_day_mean"] = (df["origin"] - pd.Timedelta(days=1) + pd.Timedelta(hours=24)) <= df["origin"]
    checks["prev_week_same_hour_mean"] = (df["hour_start"] - pd.Timedelta(hours=24) + one_h) <= df["origin"]
    log("\n=== Leakage checks (latest source hour end <= forecast origin, all 6,720 rows) ===")
    for f, ok in checks.items():
        log(f"  {f:26} {bool(ok.all())}")

    # ---------- 6. split sizes and lookback exclusion ----------
    train = df[df["split"] == "train"]
    kept = train[train["complete"]]
    log("\n=== Training lookback exclusion ===")
    log(f"Training rows before exclusion: {len(train):,}; excluded (missing lookback): "
        f"{len(train) - len(kept):,}; retained: {len(kept):,}")

    summary = []
    for name, _, _ in SPLITS:
        part = df[df["split"] == name]
        usable = part[part["complete"]]
        summary.append({"split": name, "rows": len(part), "usable_rows": len(usable),
                        "first_target": usable["hour_start"].min(),
                        "last_target": usable["hour_start"].max(),
                        "rows_missing_predictors": len(part) - len(usable)})
    log("\n=== Split sizes and date limits ===")
    log(pd.DataFrame(summary).to_string(index=False))

    # ---------- 7. feature example ----------
    ex = df[(df["region"] == "Region 1") &
            (df["hour_start"] >= pd.Timestamp("2026-09-22 18:00", tz=TZ)) &
            (df["hour_start"] <= pd.Timestamp("2026-09-22 20:00", tz=TZ))].copy()
    ex["lag_24h_source"] = ex["hour_start"] - pd.Timedelta(hours=24)
    log("\n=== Feature example (Region 1, 22 Sep 18:00-20:00) ===")
    log(ex[["region", "hour_start", "origin", "energy_kwh", "lag_24h", "lag_24h_source",
            "lag_48h", "lag_168h", "prev_day_mean", "prev_week_same_hour_mean"]]
        .to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    # ---------- save ----------
    DATA.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)
    df.to_pickle(DATA / "forecast_dataset.pkl")
    df.drop(columns=["complete"]).to_csv(OUT / "8_1_forecast_dataset.csv", index=False)
    ftab.to_csv(OUT / "8_1_features.csv", index=False)
    log(f"\nSaved data\\forecast_dataset.pkl and results\\8_1_forecast_dataset.csv ({len(df):,} rows)")
    log(f"8.1 run finished {datetime.now():%Y-%m-%d %H:%M:%S} CAT")
    (OUT / "8_1_dataset_preparation.txt").write_text("\n".join(LOG), encoding="utf-8")


if __name__ == "__main__":
    main()