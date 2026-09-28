"""Causal histories, chronological integrity and independent result reconciliation."""
import hashlib
import json
import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from londonpulse.data import load_daily, validate_history
from londonpulse.evaluation import finite_sample_radius, metrics
from londonpulse.features import FEATURE_COLUMNS, build_features, temporal_partitions
from londonpulse.inference import ForecastPredictor

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def daily():
    return load_daily(ROOT)


@pytest.fixture(scope="module")
def results():
    return json.loads((ROOT / "artifacts/results.json").read_text(encoding="utf-8"))


def test_daily_grain_and_publisher_shutdown_are_preserved(daily):
    assert len(daily) == 5877
    assert not daily["date"].duplicated().any()
    assert daily["hires"].notna().all()
    assert (daily["date"].diff().iloc[1:] == pd.Timedelta(days=1)).all()
    zeros = daily.loc[daily["hires"].eq(0), "date"].dt.strftime("%Y-%m-%d").tolist()
    assert zeros == ["2022-09-10", "2022-09-11"]


def test_appending_or_changing_future_counts_cannot_change_features(daily):
    origin = pd.Timestamp("2025-06-01")
    prefix = daily.loc[daily["date"] <= origin].tail(90)
    reference = build_features(prefix, include_targets=False)
    reference = reference.loc[reference["origin"].eq(origin), FEATURE_COLUMNS].reset_index(drop=True)
    changed = daily.loc[daily["date"].between(origin - pd.Timedelta(days=89), origin + pd.Timedelta(days=20))].copy()
    changed.loc[changed["date"] > origin, "hires"] = 99999999
    candidate = build_features(changed, include_targets=False)
    candidate = candidate.loc[candidate["origin"].eq(origin), FEATURE_COLUMNS].reset_index(drop=True)
    pd.testing.assert_frame_equal(reference, candidate)
    indexed = daily.set_index("date")["hires"]
    for horizon in range(1, 8):
        row = candidate.loc[candidate["horizon"].eq(horizon)].iloc[0]
        past = [indexed.loc[origin + pd.Timedelta(days=horizon - 7 * k)] for k in range(1, 5)]
        assert row["target_weekday_last"] == past[0]
        assert row["target_weekday_mean_4"] == pytest.approx(np.mean(past))


def test_missing_history_is_excluded_instead_of_zero_filled(daily):
    history = daily.tail(90).copy()
    origin = history["date"].max()
    history.loc[history.index[-20], "hires"] = np.nan
    features = build_features(history, include_targets=False)
    assert features.loc[features["origin"].eq(origin)].empty
    with pytest.raises(ValueError):
        validate_history(history)


def test_temporal_splits_have_unique_complete_test_weeks(daily):
    partitions = temporal_partitions(build_features(daily))
    assert partitions["fit"]["date"].max() < partitions["validation"]["date"].min()
    assert partitions["refit"]["date"].max() < partitions["calibration"]["date"].min()
    assert partitions["calibration"]["date"].max() < partitions["test"]["date"].min()
    for name, expected_weeks in (("validation", 52), ("calibration", 51), ("test", 86)):
        frame = partitions[name]
        assert frame["origin"].nunique() == expected_weeks
        assert (frame["origin"].dt.dayofweek == 6).all()
        assert not frame["date"].duplicated().any()
        assert (frame.groupby("origin")["horizon"].nunique() == 7).all()
        assert (frame["date"] - frame["origin"]).dt.days.equals(frame["horizon"])
        # Weekly planner: horizon and weekday cannot be independently interpreted.
        assert (frame["date"].dt.dayofweek == frame["horizon"] - 1).all()


def test_selected_model_uses_validation_without_test_selection(results):
    winner = min(results["models"], key=lambda row: row["validation_mae"])
    assert results["overview"]["selected_model"] == winner["id"] == "ridge"
    ridge = [row for row in results["candidates"] if row["model"] == "ridge"]
    assert results["selected_parameters"] == min(ridge, key=lambda row: row["mae"])["parameters"]


def test_all_forecast_metrics_reconcile_independently(results, daily):
    table = pd.read_csv(ROOT / "artifacts/test_forecasts.csv")
    actual = table["actual"].to_numpy()
    assert len(table) == 602
    source = daily.set_index("date")["hires"]
    assert np.array_equal(actual, source.loc[pd.to_datetime(table["date"])].to_numpy())
    for model in results["models"]:
        predicted = table[model["id"]].to_numpy()
        absolute = np.abs(predicted - actual)
        expected = {"mae": absolute.mean(), "rmse": np.sqrt(np.mean(absolute ** 2)),
                    "wape": 100 * absolute.sum() / actual.sum(),
                    "smape": 100 * np.mean(2 * absolute / (np.abs(actual) + np.abs(predicted)))}
        for key, value in expected.items():
            assert model[key] == pytest.approx(value, abs=1e-7)
    coverage = np.mean((actual >= table["lower"]) & (actual <= table["upper"]))
    width = (table["upper"] - table["lower"]).mean()
    assert results["overview"]["coverage"] == pytest.approx(coverage)
    assert results["overview"]["mean_interval_width"] == pytest.approx(width)
    assert int(coverage * len(table)) == 543


def test_calibration_radii_depend_on_calibration_rows_only(results):
    calibration = pd.read_csv(ROOT / "artifacts/calibration_forecasts.csv")
    test = pd.read_csv(ROOT / "artifacts/test_forecasts.csv")
    for horizon in range(1, 8):
        group = calibration.loc[calibration["horizon"].eq(horizon)]
        absolute = np.sort(np.abs(group["actual"] - group["prediction"]))
        rank = math.ceil((len(group) + 1) * 0.9)
        assert len(group) == 51 and rank == 47
        radius = absolute[rank - 1]
        assert results["diagnostics"]["intervals"]["radii"][str(horizon)] == pytest.approx(radius)
        points = test.loc[test["horizon"].eq(horizon)]
        assert np.allclose(points["lower"], np.maximum(0, points["prediction"] - radius))
        assert np.allclose(points["upper"], points["prediction"] + radius)


def test_saved_model_reproduces_every_test_forecast(daily, results):
    table = pd.read_csv(ROOT / "artifacts/test_forecasts.csv")
    frame = temporal_partitions(build_features(daily))["test"]
    bundle = joblib.load(ROOT / "models/model.joblib")
    prediction = np.maximum(0, bundle["model"].predict(frame[FEATURE_COLUMNS]))
    assert np.allclose(prediction, table["prediction"], atol=1e-7)
    digest = hashlib.sha256((ROOT / "models/model.joblib").read_bytes()).hexdigest()
    assert digest == results["model_sha256"]
    assert bundle["training_end"] == "2023-12-31"


def test_predictor_forecast_is_invariant_to_unused_older_history(daily):
    predictor = ForecastPredictor.from_artifacts(ROOT)
    short = predictor.forecast(daily.tail(35))
    long = predictor.forecast(daily.tail(90))
    assert short["points"] == long["points"]
    assert short["origin"] == "2026-08-31"
    assert short["points"][0]["date"] == "2026-09-01"
    assert short["points"][-1]["date"] == "2026-09-07"


def test_zero_safe_score_definition_and_finite_rank():
    assert metrics([0, 0], [0, 0]) == {"mae": 0.0, "rmse": 0.0, "wape": 0.0, "smape": 0.0}
    assert metrics([0], [1])["smape"] == 200
    assert finite_sample_radius(np.arange(1, 52)) == (47.0, 47)
    with pytest.raises(ValueError):
        finite_sample_radius([1])
