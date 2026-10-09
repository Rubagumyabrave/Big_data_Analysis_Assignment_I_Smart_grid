"""8.2 - Previous-day baseline: each test hour = same hour of the previous day."""
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results"
LOG = []


def log(text=""):
    print(text)
    LOG.append(str(text))


def mae(err):
    return float(np.mean(np.abs(err)))


def rmse(err):
    return float(np.sqrt(np.mean(np.square(err))))


def main():
    pd.set_option("display.width", 200)
    log(f"8.2 run started {datetime.now():%Y-%m-%d %H:%M:%S} CAT")
    df = pd.read_pickle(ROOT / "data" / "forecast_dataset.pkl")

    test = df[df["split"] == "test"].copy()
    test["baseline_pred"] = test["lag_24h"]                       # same hour, previous day
    test["baseline_source"] = test["hour_start"] - pd.Timedelta(hours=24)
    test["error"] = test["baseline_pred"] - test["energy_kwh"]    # predicted - actual

    assert test["baseline_pred"].notna().all(), "missing baseline values"
    assert (test["baseline_source"] + pd.Timedelta(hours=1) <= test["origin"]).all(), "leakage"

    log("\n=== Previous-day baseline on the test split (22-28 Sep) ===")
    log(f"Forecast origins: {test['origin'].nunique()} days at 00:00 CAT; "
        f"regions: {test['region'].nunique()}; hours per day: 24")
    log(f"Test predictions: {len(test):,}  (expected 7 x 24 x 10 = 1,680)")
    log(f"Every source hour precedes its origin: True")
    log(f"Baseline MAE  = {mae(test['error']):.3f} kWh")
    log(f"Baseline RMSE = {rmse(test['error']):.3f} kWh")

    log("\n=== Sample predictions (Region 1, 22 Sep 00:00-05:00 and 13:00) ===")
    sample = test[(test["region"] == "Region 1") &
                  (test["hour_start"].dt.day == 22) &
                  (test["hour_start"].dt.hour.isin([0, 1, 2, 3, 4, 5, 13]))]
    log(sample[["region", "hour_start", "origin", "baseline_source", "energy_kwh",
                "baseline_pred", "error"]].to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    log("\n=== MAE by test day (kWh) ===")
    by_day = test.groupby(test["hour_start"].dt.strftime("%a %d %b"), sort=False)["error"]
    log(pd.DataFrame({"MAE_kwh": by_day.apply(mae), "RMSE_kwh": by_day.apply(rmse)})
        .to_string(float_format=lambda v: f"{v:.3f}"))

    val = df[df["split"] == "validation"]
    verr = val["lag_24h"] - val["energy_kwh"]
    log(f"\nReference, same baseline on validation (15-21 Sep): MAE {mae(verr):.3f}, RMSE {rmse(verr):.3f} kWh")

    OUT.mkdir(exist_ok=True)
    test[["region", "hour_start", "origin", "baseline_source", "energy_kwh", "baseline_pred", "error"]] \
        .to_csv(OUT / "8_2_baseline_predictions.csv", index=False)
    log(f"\nSaved results\\8_2_baseline_predictions.csv ({len(test):,} rows)")
    log(f"8.2 run finished {datetime.now():%Y-%m-%d %H:%M:%S} CAT")
    (OUT / "8_2_baseline.txt").write_text("\n".join(LOG), encoding="utf-8")


if __name__ == "__main__":
    main()