"""Forecast from a validated daily history using the frozen artefact."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .data import validate_history
from .features import FEATURE_COLUMNS, build_features


class BaselinePredictor:
    """Importable fallback if a prespecified baseline wins validation."""
    def __init__(self, identifier: str):
        self.identifier = identifier

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return frame["target_weekday_last" if self.identifier == "seasonal_naive" else "target_weekday_mean_4"].to_numpy()


class ForecastPredictor:
    def __init__(self, bundle: dict):
        self.bundle = bundle

    @classmethod
    def from_artifacts(cls, project_dir: str | Path) -> "ForecastPredictor":
        # Load only the project's own trusted file; never accept uploaded joblib objects.
        return cls(joblib.load(Path(project_dir) / "models" / "model.joblib"))

    def forecast(self, history: pd.DataFrame | list[dict], days: int = 7) -> dict:
        if days != 7:
            raise ValueError("This model forecasts exactly seven days.")
        daily = validate_history(history)
        if len(daily) > 3000:
            raise ValueError("Use at most 3,000 daily observations.")
        origin = daily["date"].max()
        features = build_features(daily.tail(90), include_targets=False)
        rows = features.loc[features["origin"].eq(origin)].sort_values("horizon")
        if len(rows) != 7:
            raise ValueError("The final 35 days must contain complete observations.")
        with threadpool_limits(limits=2):
            prediction = np.maximum(0, self.bundle["model"].predict(rows[FEATURE_COLUMNS]))
        radii = np.array([self.bundle["radii"][str(h)] for h in rows["horizon"]])
        points = []
        for (_, row), estimate, radius in zip(rows.iterrows(), prediction, radii):
            points.append({"date": str(row["date"].date()), "horizon": int(row["horizon"]), "actual": None,
                           "prediction": round(float(estimate), 2), "lower": round(float(max(0, estimate - radius)), 2),
                           "upper": round(float(estimate + radius), 2),
                           "seasonal_naive": round(float(row["target_weekday_last"]), 2),
                           "weekday_mean": round(float(row["target_weekday_mean_4"]), 2)})
        warnings = ["Forecasts use past hire counts and future calendar dates. Weather, closures and special events are not known.",
                    "Intervals are empirical ranges calibrated on 2024. Time dependence and changing demand can affect their coverage."]
        if origin.dayofweek != 6:
            warnings.append("Benchmark ranges were calibrated on Sunday-origin forecasts. This origin shifts the target weekdays, so interval coverage for this schedule has not been assessed.")
        if origin > pd.Timestamp(self.bundle["training_end"]):
            warnings.append(f"The final history date is later than the model's training cutoff ({self.bundle['training_end']}). Predictions depend on the historical relationship remaining useful.")
        if daily["date"].min() < pd.Timestamp(self.bundle["training_start"]):
            warnings.append("Some dates precede the model's training period.")
        last_counts = daily.tail(35)["hires"]
        if last_counts.max() > self.bundle["training_count_max"] or last_counts.mean() < self.bundle["training_daily_mean"] * 0.25:
            warnings.append("Recent counts are outside or far below the model's usual training scale. Treat this as an out-of-domain forecast.")
        if (last_counts == 0).any():
            warnings.append("Recent history contains zero hires. A closed service may have different behaviour from ordinary demand.")
        return {"origin": str(origin.date()), "points": points,
                "history": [{"date": str(row.date.date()), "hires": int(row.hires)} for row in daily.tail(90).itertuples()],
                "model": self.bundle["selected_model"], "warnings": warnings,
                "nominal_coverage": self.bundle["nominal_coverage"], "training_end": self.bundle["training_end"],
                "label": "Seven-day forecast from the supplied history; no live data connection."}
