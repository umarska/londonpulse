"""Train, select, calibrate and evaluate LondonPulse without future observations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .data import SOURCE_PAGE, SOURCE_URL, file_digest, load_daily, prepare_snapshot
from .evaluation import finite_sample_radius, metrics
from .features import FEATURE_COLUMNS, build_features, temporal_partitions
from .inference import BaselinePredictor, ForecastPredictor

MODEL_NAMES = {"seasonal_naive": "Previous week, same weekday", "weekday_mean": "Four-week weekday mean",
               "ridge": "Ridge regression", "hist_gradient_boosting": "Histogram gradient boosting"}
HGB_CANDIDATES = [
    {"max_iter": 220, "max_leaf_nodes": 15, "learning_rate": 0.06, "l2_regularization": 10, "min_samples_leaf": 35},
    {"max_iter": 260, "max_leaf_nodes": 31, "learning_rate": 0.06, "l2_regularization": 10, "min_samples_leaf": 35},
    {"max_iter": 180, "max_leaf_nodes": 15, "learning_rate": 0.10, "l2_regularization": 30, "min_samples_leaf": 60},
]
NOMINAL_COVERAGE = 0.9


def dump_json(path: Path, value: dict | list) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def fit_model(identifier: str, parameters: dict, frame: pd.DataFrame):
    if identifier == "ridge":
        model = make_pipeline(StandardScaler(), Ridge(**parameters))
    elif identifier == "hist_gradient_boosting":
        model = HistGradientBoostingRegressor(**parameters, early_stopping=False, random_state=42)
    else:
        return None
    with threadpool_limits(limits=2):
        model.fit(frame[FEATURE_COLUMNS], frame["actual"])
    return model


def predict(identifier: str, model, frame: pd.DataFrame) -> np.ndarray:
    if identifier == "seasonal_naive":
        values = frame["target_weekday_last"].to_numpy()
    elif identifier == "weekday_mean":
        values = frame["target_weekday_mean_4"].to_numpy()
    else:
        with threadpool_limits(limits=2):
            values = model.predict(frame[FEATURE_COLUMNS])
    return np.maximum(0, values)


def forecast_table(frame: pd.DataFrame, fitted: dict) -> pd.DataFrame:
    table = frame[["origin", "date", "horizon", "actual"]].copy()
    for identifier, model in fitted.items():
        table[identifier] = predict(identifier, model, frame)
    return table


def period_info(frame: pd.DataFrame) -> dict:
    return {"origins": int(frame["origin"].nunique()), "rows": int(len(frame)),
            "origin_start": str(frame["origin"].min().date()), "origin_end": str(frame["origin"].max().date()),
            "target_start": str(frame["date"].min().date()), "target_end": str(frame["date"].max().date())}


def round_scores(values: dict) -> dict:
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in values.items()}


def plot_figures(project_dir: Path, daily: pd.DataFrame, table: pd.DataFrame, results: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    folder = project_dir / "artifacts" / "figures"
    folder.mkdir(exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.facecolor": "#f4f7fa", "axes.facecolor": "#f4f7fa"})
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(daily["date"], daily["hires"].rolling(28).mean(), color="#138a72", linewidth=1.5)
    for date, label, colour in [("2023-01-01", "Validation", "#d38c23"), ("2024-01-01", "Calibration", "#bd5db6"), ("2025-01-01", "Test", "#2861b3")]:
        ax.axvline(pd.Timestamp(date), color=colour, linestyle="--", linewidth=1)
        ax.text(pd.Timestamp(date), ax.get_ylim()[1] * .92, label, color=colour, rotation=90, va="top")
    ax.set(title="London cycle hires: 28-day mean and chronological evaluation", ylabel="Hires per day", xlabel="Date")
    fig.tight_layout(); fig.savefig(folder / "history.png", dpi=150); plt.close(fig)
    models = results["models"]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.barh([m["name"] for m in models][::-1], [m["mae"] for m in models][::-1], color=["#d9ad69", "#b0bdce", "#6a8abb", "#138a72"])
    ax.set(title="Untouched test weeks: average absolute forecast error", xlabel="MAE, hires per day")
    fig.tight_layout(); fig.savefig(folder / "comparison.png", dpi=150); plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.3))
    h = pd.DataFrame(results["diagnostics"]["by_horizon"])
    axes[0].plot(h["horizon"], h["mae"], marker="o", color="#138a72")
    axes[0].set(title="Error by forecast horizon", xlabel="Days ahead", ylabel="MAE, hires")
    axes[1].bar(h["horizon"], h["coverage"] * 100, color="#138a72")
    axes[1].axhline(90, linestyle="--", color="#d38c23", label="Nominal 90%")
    axes[1].set(title="Observed test interval coverage", xlabel="Days ahead", ylabel="Coverage, %", ylim=(0, 100))
    axes[1].legend(frameon=False)
    fig.tight_layout(); fig.savefig(folder / "horizons.png", dpi=150); plt.close(fig)
    # First eight test weeks: a reproducible illustration chosen by chronology, not error.
    subset = table.loc[table["origin"].isin(sorted(table["origin"].unique())[:8])]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.fill_between(subset["date"], subset["lower"], subset["upper"], alpha=.18, color="#138a72", label="Empirical 90% range")
    ax.plot(subset["date"], subset["prediction"], color="#138a72", label="Forecast")
    ax.plot(subset["date"], subset["actual"], color="#21364b", linewidth=1.2, label="Observed hires")
    ax.set(title="First eight test weeks: seven-day forecasts from each Sunday", ylabel="Daily hires", xlabel="Target date")
    ax.legend(frameon=False, ncol=3); fig.tight_layout(); fig.savefig(folder / "test_forecasts.png", dpi=150); plt.close(fig)


def train(project_dir: str | Path, workbook: str | Path | None = None, skip_download: bool = False) -> dict:
    started = time.monotonic()
    project_dir = Path(project_dir)
    artifacts = project_dir / "artifacts"; artifacts.mkdir(parents=True, exist_ok=True)
    model_dir = project_dir / "models"; model_dir.mkdir(exist_ok=True)
    if not skip_download:
        prepare_snapshot(project_dir, workbook)
    daily = load_daily(project_dir)
    provenance = json.loads((project_dir / "data" / "processed" / "provenance.json").read_text(encoding="utf-8"))
    features = build_features(daily)
    partitions = temporal_partitions(features)
    fit, validation, calibration, test = (partitions[name] for name in ("fit", "validation", "calibration", "test"))
    print(f"Usable training rows: {len(fit):,}; validation/calibration/test weeks: "
          f"{validation.origin.nunique()}/{calibration.origin.nunique()}/{test.origin.nunique()}", flush=True)
    candidates = []
    settings = {"seasonal_naive": [{}], "weekday_mean": [{}], "ridge": [{"alpha": 10.0}, {"alpha": 100.0}],
                "hist_gradient_boosting": HGB_CANDIDATES}
    best = {}
    for identifier, configurations in settings.items():
        for parameters in configurations:
            model = fit_model(identifier, parameters, fit)
            scores = metrics(validation["actual"], predict(identifier, model, validation))
            candidate = {"model": identifier, "parameters": parameters, **scores}
            candidates.append(candidate)
            if identifier not in best or scores["mae"] < best[identifier]["scores"]["mae"]:
                best[identifier] = {"parameters": parameters, "scores": scores}
            print(f"Validation {identifier}: MAE {scores['mae']:.2f}", flush=True)
    selected = min(best, key=lambda identifier: best[identifier]["scores"]["mae"])
    # Baselines can win selection; retain a small picklable adapter for inference.
    fitted = {identifier: fit_model(identifier, detail["parameters"], partitions["refit"]) for identifier, detail in best.items()}
    calibration_table = forecast_table(calibration, fitted)
    calibration_table["prediction"] = calibration_table[selected]
    calibration_table["absolute_error"] = abs(calibration_table["prediction"] - calibration_table["actual"])
    radii, ranks = {}, {}
    for horizon, group in calibration_table.groupby("horizon"):
        radius, rank = finite_sample_radius(group["absolute_error"], NOMINAL_COVERAGE)
        radii[str(int(horizon))] = radius; ranks[str(int(horizon))] = rank
    counts = daily.loc[daily["date"].between("2015-01-01", "2023-12-31"), "hires"]
    final_model = fitted[selected] if fitted[selected] is not None else BaselinePredictor(selected)
    bundle = {"model": final_model, "selected_model": selected, "parameters": best[selected]["parameters"],
              "features": FEATURE_COLUMNS, "radii": radii, "nominal_coverage": NOMINAL_COVERAGE,
              "training_start": "2015-01-01", "training_end": "2023-12-31",
              "training_count_max": float(counts.max()), "training_daily_mean": float(counts.mean()),
              "source_sha256": provenance["source_sha256"], "processed_sha256": provenance["processed_sha256"]}
    # Serialise the frozen model and calibration before using the test observations.
    model_path = model_dir / "model.joblib"
    joblib.dump(bundle, model_path, compress=3)
    test_table = forecast_table(test, fitted)
    test_table["prediction"] = test_table[selected]
    test_table["radius"] = test_table["horizon"].map(lambda h: radii[str(int(h))])
    test_table["lower"] = np.maximum(0, test_table["prediction"] - test_table["radius"])
    test_table["upper"] = test_table["prediction"] + test_table["radius"]
    test_table["residual"] = test_table["prediction"] - test_table["actual"]
    test_table["covered"] = test_table["actual"].between(test_table["lower"], test_table["upper"])
    validation_table = forecast_table(validation, {identifier: fit_model(identifier, detail["parameters"], fit) for identifier, detail in best.items()})
    for name, frame in [("test_forecasts", test_table), ("calibration_forecasts", calibration_table), ("validation_forecasts", validation_table)]:
        frame.to_csv(artifacts / f"{name}.csv", index=False, date_format="%Y-%m-%d", float_format="%.10f")
    model_scores = [{"id": identifier, "name": MODEL_NAMES[identifier],
                     "validation_mae": best[identifier]["scores"]["mae"],
                     **metrics(test_table["actual"], test_table[identifier])} for identifier in best]
    selected_scores = metrics(test_table["actual"], test_table["prediction"])
    baseline_mae = metrics(test_table["actual"], test_table["seasonal_naive"])["mae"]
    overview = {"selected_model": selected, "selected_name": MODEL_NAMES[selected], **selected_scores,
                "baseline_improvement_percent": 100 * (1 - selected_scores["mae"] / baseline_mae),
                "coverage": float(test_table["covered"].mean()),
                "mean_interval_width": float((test_table["upper"] - test_table["lower"]).mean()),
                "test_weeks": int(test_table["origin"].nunique()), "test_days": int(len(test_table)),
                "nominal_coverage": NOMINAL_COVERAGE}
    diagnostics = {"by_horizon": [], "by_weekday": [], "monthly": [],
                   "intervals": {"nominal_coverage": NOMINAL_COVERAGE, "coverage": overview["coverage"],
                                 "mean_width": overview["mean_interval_width"], "radii": radii, "finite_ranks": ranks,
                                 "calibration_weeks": int(calibration.origin.nunique())}}
    for horizon, group in test_table.groupby("horizon"):
        diagnostics["by_horizon"].append({"horizon": int(horizon), **metrics(group["actual"], group["prediction"]),
                                          "coverage": float(group["covered"].mean()),
                                          "mean_width": float((group["upper"] - group["lower"]).mean()), "count": int(len(group))})
    for day in range(7):
        group = test_table.loc[test_table["date"].dt.dayofweek.eq(day)]
        diagnostics["by_weekday"].append({"weekday": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][day],
                                          "weekday_number": day, **metrics(group["actual"], group["prediction"]), "count": int(len(group))})
    for month, group in test_table.groupby(test_table["date"].dt.strftime("%Y-%m")):
        diagnostics["monthly"].append({"month": month, **metrics(group["actual"], group["prediction"]),
                                      "coverage": float(group["covered"].mean()), "count": int(len(group))})
    split = {name: period_info(frame) for name, frame in partitions.items()}
    split.update({"selection_metric": "Validation MAE", "evaluation_origin_weekday": "Sunday",
                  "training_target_start": "2015-01-01", "training_target_end": "2022-12-31",
                  "final_training_target_end": "2023-12-31", "calibration_target_year": 2024,
                  "unused_early_history": "2010–2014 counts remain visible and supply lag context; their targets are excluded from training to avoid scheme launch ramp-up.",
                  "training_targets_repeated": "Each observed training date can be a target at seven origins/horizons. Evaluation weeks have unique target dates."})
    metadata = {"source_url": SOURCE_PAGE, "download_url": SOURCE_URL, "source_cutoff": str(daily.date.max().date()),
                "data_start": str(daily.date.min().date()), "data_end": str(daily.date.max().date()),
                "train_start": "2015-01-01", "train_end": "2023-12-31", "initial_train_end": "2022-12-31",
                "validation_start": split["validation"]["target_start"], "validation_end": split["validation"]["target_end"],
                "calibration_start": split["calibration"]["target_start"], "calibration_end": split["calibration"]["target_end"],
                "test_start": split["test"]["target_start"], "test_end": split["test"]["target_end"],
                "publisher": "Transport for London", "licence": "Open Government Licence v2.0", "licence_url": provenance["licence_url"],
                "snapshot_label": "Pinned TfL snapshot through 31 August 2026; no live data connection.", "feature_count": len(FEATURE_COLUMNS)}
    results = {"metadata": metadata, "overview": overview, "models": model_scores, "diagnostics": diagnostics,
               "candidates": candidates, "selected_parameters": best[selected]["parameters"], "splits": split,
               "model_sha256": file_digest(model_path), "features": FEATURE_COLUMNS,
               "protocol": "Candidates and split dates specified before test scoring. Models selected on 2023 validation MAE, refitted through 2023, then ranges frozen on 2024 before test scoring.",
               "limitations": ["Temporal residuals are dependent. Finite-rank correction does not establish distribution-free coverage for this time series.",
                               "Sunday-origin evaluation makes forecast horizon and target weekday inseparable. Coverage on other origin weekdays has not been assessed.",
                               "The benchmark uses one revised publisher snapshot, not as-published data vintages. Historical counts may differ slightly from those available on the original forecast dates.",
                               "Weather, future closures, bank holidays and special events are not explicit model inputs.",
                               "The target measures completed scheme hires, not unmet demand, unique riders or station-level needs.",
                               "2025–2026 may differ from the pre-2024 training regime; test diagnostics report this observed shift."],
               "training_seconds": round(time.monotonic() - started, 2)}
    dump_json(artifacts / "results.json", results)
    dump_json(artifacts / "splits.json", split)
    dump_json(artifacts / "provenance.json", provenance)
    weeks = []
    for index, (origin, group) in enumerate(test_table.groupby("origin")):
        rows = []
        for row in group.itertuples():
            rows.append({"date": str(row.date.date()), "horizon": int(row.horizon), "actual": int(row.actual),
                         "prediction": round(float(row.prediction), 2), "lower": round(float(row.lower), 2), "upper": round(float(row.upper), 2),
                         "seasonal_naive": round(float(row.seasonal_naive), 2), "weekday_mean": round(float(row.weekday_mean), 2),
                         "ridge": round(float(row.ridge), 2)})
        history = daily.loc[daily["date"].between(origin - pd.Timedelta(days=89), origin)]
        weeks.append({"id": str(origin.date()), "origin": str(origin.date()),
                      "label": f"{group.date.min():%d %b}–{group.date.max():%d %b %Y}", "points": rows,
                      "mae": metrics(group["actual"], group["prediction"])["mae"],
                      "history": [{"date": str(row.date.date()), "hires": int(row.hires)} for row in history.itertuples()]})
    next_forecast = ForecastPredictor(bundle).forecast(daily.tail(90))
    next_forecast["label"] = "Illustrative forecast from history ending 31 August 2026, using one revised source snapshot. It is not today's forecast."
    next_forecast["warnings"].append("The source snapshot ends on 31 August 2026. Actual outcomes after that date are not included or verified.")
    demo = {"metadata": metadata, "overview": overview, "models": model_scores, "diagnostics": diagnostics,
            "history": [{"date": str(row.date.date()), "hires": int(row.hires) if not pd.isna(row.hires) else None} for row in daily.itertuples()],
            "weeks": weeks, "next_forecast": next_forecast, "quality": provenance["quality"]}
    dump_json(artifacts / "demo.json", demo)
    examples = project_dir / "data" / "examples"; examples.mkdir(exist_ok=True)
    daily.tail(90).to_csv(examples / "sample.csv", index=False, date_format="%Y-%m-%d", float_format="%.0f")
    plot_figures(project_dir, daily, test_table, results)
    print(json.dumps({"overview": round_scores(overview), "models": [round_scores(m) for m in model_scores], "radii": radii}, indent=2), flush=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce LondonPulse's chronological forecast benchmark.")
    parser.add_argument("--project-dir", default=str(Path.cwd()), help="Repository directory; defaults to the current working directory.")
    parser.add_argument("--workbook", default=None, help="Path to the verified publisher workbook.")
    parser.add_argument("--skip-download", action="store_true", help="Verify and use the tracked processed snapshot offline.")
    args = parser.parse_args()
    train(args.project_dir, args.workbook, args.skip_download)


if __name__ == "__main__":
    main()
