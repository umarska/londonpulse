"""Direct seven-day features whose observations never pass the forecast origin."""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_COLUMNS = ["horizon", "origin_hires", "lag_1", "lag_7", "lag_14", "lag_28",
                   "rolling_7_mean", "rolling_7_std", "rolling_28_mean", "rolling_28_std",
                   "week_change", "target_weekday_last", "target_weekday_mean_4", "target_weekday_std_4",
                   "weekday_sin", "weekday_cos", "month_sin", "month_cos", "year_sin", "year_cos",
                   "time_years"]
FEATURE_START = pd.Timestamp("2010-07-30")


def build_features(daily: pd.DataFrame, include_targets: bool = True) -> pd.DataFrame:
    """One row per origin/horizon. Missing 35-day histories are dropped, never imputed."""
    frame = daily[["date", "hires"]].copy().set_index("date").sort_index()
    frame = frame.reindex(pd.date_range(frame.index.min(), frame.index.max(), freq="D"))
    y = frame["hires"].astype(float)
    origins = y.index
    base = pd.DataFrame(index=origins)
    base["origin_hires"] = y
    for lag in (1, 7, 14, 28):
        base[f"lag_{lag}"] = y.shift(lag)
    for window in (7, 28):
        base[f"rolling_{window}_mean"] = y.rolling(window, min_periods=window).mean()
        base[f"rolling_{window}_std"] = y.rolling(window, min_periods=window).std(ddof=0)
    base["week_change"] = y.rolling(7).mean() - y.shift(7).rolling(7).mean()
    complete_history = y.rolling(35, min_periods=35).count().eq(35)
    rows = []
    for horizon in range(1, 8):
        block = base.copy()
        target_dates = origins + pd.Timedelta(days=horizon)
        prior_weekdays = pd.concat([y.shift(7 * k - horizon) for k in range(1, 5)], axis=1)
        block["target_weekday_last"] = prior_weekdays.iloc[:, 0]
        block["target_weekday_mean_4"] = prior_weekdays.mean(axis=1)
        block["target_weekday_std_4"] = prior_weekdays.std(axis=1, ddof=0)
        block["horizon"] = horizon
        weekday = target_dates.dayofweek.to_numpy()
        month = target_dates.month.to_numpy() - 1
        # 365.2425 days gives a continuous, known calendar seasonal representation.
        doy = target_dates.dayofyear.to_numpy() - 1
        block["weekday_sin"] = np.sin(2 * np.pi * weekday / 7)
        block["weekday_cos"] = np.cos(2 * np.pi * weekday / 7)
        block["month_sin"] = np.sin(2 * np.pi * month / 12)
        block["month_cos"] = np.cos(2 * np.pi * month / 12)
        block["year_sin"] = np.sin(2 * np.pi * doy / 365.2425)
        block["year_cos"] = np.cos(2 * np.pi * doy / 365.2425)
        block["time_years"] = (target_dates - FEATURE_START).days / 365.2425
        block["origin"] = origins
        block["date"] = target_dates
        if include_targets:
            block["actual"] = y.shift(-horizon)
        block = block.loc[complete_history]
        required = FEATURE_COLUMNS + (["actual"] if include_targets else [])
        rows.append(block.dropna(subset=required).reset_index(drop=True))
    return pd.concat(rows, ignore_index=True).sort_values(["origin", "horizon"]).reset_index(drop=True)


def temporal_partitions(features: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Daily target training; whole non-overlapping Sunday-origin evaluation weeks."""
    target = features["date"]
    fit = features.loc[target.between("2015-01-01", "2022-12-31")].copy()
    refit = features.loc[target.between("2015-01-01", "2023-12-31")].copy()
    groups = {"fit": fit, "refit": refit}
    bounds = {"validation": ("2023-01-01", "2023-12-31"), "calibration": ("2024-01-01", "2024-12-31"),
              "test": ("2025-01-01", str(target.max().date()))}
    for name, (start, end) in bounds.items():
        mask = (features["origin"].dt.dayofweek == 6) & (features["origin"] >= pd.Timestamp(start))
        block = features.loc[mask & (target <= pd.Timestamp(end))].copy()
        complete = block.groupby("origin")["horizon"].agg(["count", "nunique"])
        valid_origins = complete.index[(complete["count"] == 7) & (complete["nunique"] == 7)]
        groups[name] = block.loc[block["origin"].isin(valid_origins)].reset_index(drop=True)
    if any(groups[name].empty for name in groups):
        raise ValueError("A chronological partition has no usable observations.")
    return groups
