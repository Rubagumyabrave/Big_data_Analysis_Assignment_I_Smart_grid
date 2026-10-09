"""8.4 - Forecast usefulness: overall / per-region metrics, peak hours, plot."""
from datetime import datetime
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results"
TZ = "Africa/Kigali"
PLOT_REGION = "Region 1"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE = "#2a78d6", "#eb6834"
LOG = []


def log(text=""):
    print(text)
    LOG.append(str(text))


def mae(err):
    return float(np.mean(np.abs(err)))


def rmse(err):
    return float(np.sqrt(np.mean(np.square(err))))


def metrics(g):
    eb, em = g["baseline_pred"] - g["energy_kwh"], g["model_pred"] - g["energy_kwh"]
    return pd.Series({"n": len(g), "baseline_MAE": mae(eb), "model_MAE": mae(em),
                      "baseline_RMSE": rmse(eb), "model_RMSE": rmse(em)})


def main():
    pd.set_option("display.width", 200)
    log(f"8.4 run started {datetime.now():%Y-%m-%d %H:%M:%S} CAT")
    t = pd.read_csv(OUT / "8_3_test_predictions.csv")
    t["hour_start"] = pd.to_datetime(t["hour_start"], utc=True).dt.tz_convert(TZ)
    t["rnum"] = t["region"].str.split().str[-1].astype(int)
    t = t.sort_values(["rnum", "hour_start"]).reset_index(drop=True)
    f2 = lambda v: f"{v:.3f}"

    # ---------- overall ----------
    eb, em = t["baseline_pred"] - t["energy_kwh"], t["model_pred"] - t["energy_kwh"]
    overall = pd.DataFrame([
        {"method": "previous-day baseline", "MAE_kwh": mae(eb), "RMSE_kwh": rmse(eb), "n": len(t)},
        {"method": "Ridge R1 (alpha=0.1)", "MAE_kwh": mae(em), "RMSE_kwh": rmse(em), "n": len(t)}])
    log("\n=== Test metrics, all 1,680 observations (error = predicted - actual) ===")
    log(overall.to_string(index=False, float_format=f2))
    log(f"MAE improvement: {100 * (1 - mae(em) / mae(eb)):.1f} %   "
        f"RMSE improvement: {100 * (1 - rmse(em) / rmse(eb)):.1f} %")
    mean_actual = t["energy_kwh"].mean()
    log(f"Mean actual hourly regional consumption: {mean_actual:.1f} kWh "
        f"(model MAE = {100 * mae(em) / mean_actual:.2f} % of mean, baseline {100 * mae(eb) / mean_actual:.2f} %)")
    log(f"Mean error (bias): baseline {eb.mean():+.3f} kWh, model {em.mean():+.3f} kWh")

    # ---------- per region ----------
    by_region = t.groupby(["rnum", "region"]).apply(metrics, include_groups=False) \
                 .reset_index().drop(columns="rnum")
    by_region["n"] = by_region["n"].astype(int)
    log("\n=== Per region (kWh, 168 test hours each) ===")
    log(by_region.to_string(index=False, float_format=f2))

    # ---------- per day ----------
    day = t["hour_start"].dt.strftime("%a %d %b")
    by_day = t.groupby(day, sort=False).apply(metrics, include_groups=False)
    by_day["n"] = by_day["n"].astype(int)
    log("\n=== Per test day (kWh, 240 observations each) ===")
    log(by_day.to_string(float_format=f2))

    # ---------- peak hour per region ----------
    idx = t.groupby("rnum")["energy_kwh"].idxmax()          # first max = earliest (sorted by time)
    peaks = t.loc[idx, ["region", "hour_start", "energy_kwh", "baseline_pred", "model_pred"]].copy()
    peaks["baseline_abs_err"] = (peaks["baseline_pred"] - peaks["energy_kwh"]).abs()
    peaks["model_abs_err"] = (peaks["model_pred"] - peaks["energy_kwh"]).abs()
    peaks["hour_start"] = peaks["hour_start"].dt.strftime("%a %Y-%m-%d %H:%M")
    log("\n=== Highest actual test hour per region (ties -> earliest) ===")
    log(peaks.to_string(index=False, float_format=f2))
    log(f"Mean absolute error at the peak hours: baseline {peaks['baseline_abs_err'].mean():.3f}, "
        f"model {peaks['model_abs_err'].mean():.3f} kWh")

    # ---------- plot ----------
    r = t[t["region"] == PLOT_REGION]
    fig, ax = plt.subplots(figsize=(13, 4.8), dpi=150)
    for d in pd.date_range("2026-09-22", periods=7, freq="D", tz=TZ):
        if d.dayofweek >= 5:
            ax.axvspan(d, d + pd.Timedelta(days=1), color=GRID, alpha=0.6, lw=0)
            ax.text(d + pd.Timedelta(hours=12), 0.98, "weekend", transform=ax.get_xaxis_transform(),
                    ha="center", va="top", color=MUTED, fontsize=9)
    ax.plot(r["hour_start"], r["energy_kwh"], color=INK, lw=2.0, label="Actual")
    ax.plot(r["hour_start"], r["baseline_pred"], color=ORANGE, lw=1.6, ls="--",
            label=f"Previous-day baseline (MAE {mae(r['baseline_pred'] - r['energy_kwh']):.1f} kWh)")
    ax.plot(r["hour_start"], r["model_pred"], color=BLUE, lw=1.6,
            label=f"Ridge R1 (MAE {mae(r['model_pred'] - r['energy_kwh']):.1f} kWh)")
    ax.set_title(f"{PLOT_REGION}: actual vs forecast hourly consumption, test week 22-28 Sep 2026 (CAT)",
                 loc="left", color=INK, fontsize=12)
    ax.set_ylabel("Energy per hour (kWh)", color=MUTED)
    ax.xaxis.set_major_locator(matplotlib.dates.DayLocator(tz=r["hour_start"].dt.tz))
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%a %d %b", tz=r["hour_start"].dt.tz))
    ax.grid(axis="y", color=GRID, lw=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED)
    ax.legend(loc="lower left", frameon=False, ncol=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "figures/8_4_forecast_region1.png")
    plt.close(fig)

    overall.to_csv(OUT / "8_4_overall_metrics.csv", index=False)
    by_region.to_csv(OUT / "8_4_region_metrics.csv", index=False)
    by_day.to_csv(OUT / "8_4_day_metrics.csv")
    peaks.to_csv(OUT / "8_4_peak_hours.csv", index=False)
    log("\nSaved results\\8_4_overall_metrics.csv, _region_metrics.csv, _day_metrics.csv, "
        "_peak_hours.csv, 8_4_forecast_region1.png")
    log(f"8.4 run finished {datetime.now():%Y-%m-%d %H:%M:%S} CAT")
    (OUT / "8_4_evaluation.txt").write_text("\n".join(LOG), encoding="utf-8")


if __name__ == "__main__":
    main()