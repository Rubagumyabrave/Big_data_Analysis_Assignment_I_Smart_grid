"""8.3 - Ridge regression: train configurations, select on validation MAE, freeze, test."""
import time
from datetime import datetime
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
OUT, DATA = ROOT / "results", ROOT / "data"
NUMERIC = ["lag_24h", "lag_48h", "lag_168h", "prev_day_mean", "prev_week_same_hour_mean"]
CATEGORICAL = ["region", "hour", "dow"]
CONFIGS = {"R1": 0.1, "R2": 1.0, "R3": 10.0, "R4": 100.0}
LOG = []


def log(text=""):
    print(text)
    LOG.append(str(text))


def mae(err):
    return float(np.mean(np.abs(err)))


def rmse(err):
    return float(np.sqrt(np.mean(np.square(err))))


def make_pipeline(alpha):
    prep = ColumnTransformer([
        ("num", StandardScaler(), NUMERIC),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
    ])
    return Pipeline([("prep", prep), ("model", Ridge(alpha=alpha))])


def main():
    pd.set_option("display.width", 200)
    log(f"8.3 run started {datetime.now():%Y-%m-%d %H:%M:%S} CAT")
    df = pd.read_pickle(DATA / "forecast_dataset.pkl")
    df["hour"] = df["hour"].astype(str)          # treat as categories, not numbers
    df["dow"] = df["dow"].astype(str)

    train = df[(df["split"] == "train") & df["complete"]]
    val = df[(df["split"] == "validation") & df["complete"]]
    test = df[(df["split"] == "test") & df["complete"]].copy()
    X = NUMERIC + CATEGORICAL

    log(f"\nShared predictors: numeric {NUMERIC} (standardised), categorical {CATEGORICAL} (one-hot)")
    log("Preprocessing (scaler + encoder) is fitted on training rows only, inside each pipeline.")
    log(f"Training rows: {len(train):,} ({train['hour_start'].min():%d %b %H:%M} - "
        f"{train['hour_start'].max():%d %b %H:%M}); validation rows: {len(val):,}")

    # ---------- train every configuration on the same training rows ----------
    rows, fitted = [], {}
    for cid, alpha in CONFIGS.items():
        pipe = make_pipeline(alpha)
        t0 = time.perf_counter()
        pipe.fit(train[X], train["energy_kwh"])
        secs = time.perf_counter() - t0
        err = pipe.predict(val[X]) - val["energy_kwh"]
        rows.append({"config": cid, "settings": f"Ridge(alpha={alpha})", "train_rows": len(train),
                     "validation_rows": len(val), "validation_mae_kwh": mae(err),
                     "validation_rmse_kwh": rmse(err), "fit_seconds": secs})
        fitted[cid] = pipe
    table = pd.DataFrame(rows)
    log("\n=== Training complete - validation comparison ===")
    log(table.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    berr = val["lag_24h"] - val["energy_kwh"]
    log(f"(Previous-day baseline on validation: MAE {mae(berr):.3f}, RMSE {rmse(berr):.3f} kWh)")

    # ---------- select and freeze ----------
    best = table.loc[table["validation_mae_kwh"].idxmin()]
    frozen_path = DATA / "forecast_model_frozen.joblib"
    joblib.dump(fitted[best["config"]], frozen_path)
    log(f"\nSelected {best['config']} ({best['settings']}), lowest validation MAE "
        f"{best['validation_mae_kwh']:.3f} kWh")
    log(f"Frozen fitted pipeline (preprocessing + model) saved to data\\{frozen_path.name}; "
        f"no refitting on validation or test data.")

    # ---------- test with the frozen model ----------
    frozen = joblib.load(frozen_path)
    test["model_pred"] = frozen.predict(test[X])
    test["baseline_pred"] = test["lag_24h"]
    lag_ok = (test["hour_start"] - pd.Timedelta(hours=24) + pd.Timedelta(hours=1) <= test["origin"]).all()
    log("\n=== Test predictions with the frozen model (22-28 Sep) ===")
    log(f"Test predictions: {len(test):,} (same rows as the baseline: "
        f"{test['baseline_pred'].notna().sum():,}); every lag source precedes its origin: {bool(lag_ok)}")

    sample = test[(test["region"] == "Region 1") & (test["hour_start"].dt.day == 22) &
                  (test["hour_start"].dt.hour.isin([0, 1, 2, 3, 4, 13]))]
    log("\nSample test predictions (Region 1, 22 Sep):")
    log(sample[["region", "hour_start", "energy_kwh", "baseline_pred", "model_pred"]]
        .to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    OUT.mkdir(exist_ok=True)
    table.to_csv(OUT / "8_3_validation_comparison.csv", index=False)
    test[["region", "hour_start", "origin", "energy_kwh", "baseline_pred", "model_pred"]] \
        .to_csv(OUT / "8_3_test_predictions.csv", index=False)
    log(f"\nSaved results\\8_3_validation_comparison.csv and 8_3_test_predictions.csv ({len(test):,} rows)")
    log(f"8.3 run finished {datetime.now():%Y-%m-%d %H:%M:%S} CAT")
    (OUT / "8_3_model.txt").write_text("\n".join(LOG), encoding="utf-8")


if __name__ == "__main__":
    main()