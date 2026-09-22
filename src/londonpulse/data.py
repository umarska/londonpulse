"""Verify the TfL source snapshot and enforce the daily observation grain."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.request

import numpy as np
import pandas as pd

SOURCE_URL = "https://data.london.gov.uk/download/2r84d/ac29363e-e0cb-47cc-a97a-e216d900a6b0/tfl-daily-cycle-hires.xlsx"
SOURCE_PAGE = "https://data.london.gov.uk/dataset/number-of-bicycle-hires-2r84d"
SOURCE_SHA256 = "82b9bd20ca2dd06fc3906e6287c7ff98022d48f0e015add99d818cf99adab829"
LICENCE_URL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/2/"


def file_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_history(rows: pd.DataFrame | list[dict], minimum_days: int = 35) -> pd.DataFrame:
    """Validate consecutive, ordered daily counts; never replace missing data with zero."""
    frame = pd.DataFrame(rows).copy()
    if not {"date", "hires"}.issubset(frame.columns):
        raise ValueError("Use two columns named date and hires.")
    frame = frame[["date", "hires"]]
    try:
        dates = pd.to_datetime(frame["date"], errors="raise")
        if getattr(dates.dt, "tz", None) is not None:
            raise ValueError("Use calendar dates without time zones.")
        if (dates != dates.dt.normalize()).any():
            raise ValueError("Use calendar dates without a time of day.")
        counts = pd.to_numeric(frame["hires"], errors="raise").to_numpy(dtype=float)
    except (TypeError, OverflowError, pd.errors.OutOfBoundsDatetime) as error:
        raise ValueError("Dates and hire counts must be valid numbers and dates.") from error
    if dates.isna().any() or not dates.between("1900-01-01", "2100-12-31").all():
        raise ValueError("Dates must fall between 1900 and 2100.")
    if len(frame) < minimum_days:
        raise ValueError(f"Provide at least {minimum_days} consecutive days of history.")
    if not dates.is_monotonic_increasing or dates.duplicated().any():
        raise ValueError("Dates must be unique and in increasing order.")
    if not (dates.diff().iloc[1:] == pd.Timedelta(days=1)).all():
        raise ValueError("Provide consecutive days; missing counts are not treated as zero.")
    if not np.isfinite(counts).all() or (counts < 0).any() or (counts > 1e8).any():
        raise ValueError("Hire counts must be finite integers from 0 to 100,000,000.")
    if not (counts == np.floor(counts)).all():
        raise ValueError("Hire counts must be whole numbers.")
    frame["date"] = dates
    frame["hires"] = counts
    return frame.reset_index(drop=True)


def read_workbook(path: str | Path) -> tuple[pd.DataFrame, dict]:
    """Read only daily columns B/C, excluding neighbouring monthly and annual totals."""
    path = Path(path)
    actual_hash = file_digest(path)
    if actual_hash != SOURCE_SHA256:
        raise ValueError("The publisher file differs from the pinned snapshot. Review the revision before updating its hash.")
    raw = pd.read_excel(path, sheet_name="Data", header=5, usecols="B:C", engine="openpyxl")
    if list(raw.columns) != ["Day", "Number of Bicycle Hires"]:
        raise ValueError("The workbook's daily schema changed.")
    raw.columns = ["date", "hires"]
    # Preserve publisher-reported zeros, including the documented 2022 shutdown.
    raw = raw.loc[raw["date"].notna()].copy()
    raw["date"] = pd.to_datetime(raw["date"], errors="raise").dt.normalize()
    raw["hires"] = pd.to_numeric(raw["hires"], errors="raise")
    if raw["date"].duplicated().any() or not raw["date"].is_monotonic_increasing:
        raise ValueError("Source dates are duplicated or not ordered.")
    known = raw["hires"].dropna().to_numpy(dtype=float)
    if not np.isfinite(known).all() or (known < 0).any() or (known != np.floor(known)).any():
        raise ValueError("Invalid source hire counts.")
    frame = raw.set_index("date").reindex(pd.date_range(raw["date"].min(), raw["date"].max(), freq="D"))
    frame.index.name = "date"
    frame = frame.reset_index()
    missing = frame.loc[frame["hires"].isna(), "date"].dt.strftime("%Y-%m-%d").tolist()
    quality = {
        "source_rows": int(len(raw)), "calendar_rows": int(len(frame)),
        "missing_dates": missing, "duplicate_dates": 0,
        "zero_dates": frame.loc[frame["hires"].eq(0), "date"].dt.strftime("%Y-%m-%d").tolist(),
        "data_start": str(frame["date"].min().date()), "data_end": str(frame["date"].max().date()),
        "total_hires": int(frame["hires"].sum()), "minimum": int(known.min()), "maximum": int(known.max()),
        "missing_policy": "Missing days remain blank. Origins requiring any missing history or target are excluded.",
        "source_notes": ["The source reports zero hires on 10–11 September 2022 and documents a full scheme shutdown. These are retained as observed service counts, not interpreted as zero underlying demand.",
                         "From 1 August 2017, delayed system events can revise daily figures. Counts usually stabilise after two weeks."],
    }
    return frame, quality


def prepare_snapshot(project_dir: str | Path, workbook: str | Path | None = None) -> dict:
    project_dir = Path(project_dir)
    raw_dir = project_dir / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = Path(workbook) if workbook else raw_dir / "tfl-daily-cycle-hires.xlsx"
    if not path.exists():
        request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "LondonPulse/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            path.write_bytes(response.read())
    frame, quality = read_workbook(path)
    processed_dir = project_dir / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    destination = processed_dir / "daily.csv"
    frame.to_csv(destination, index=False, date_format="%Y-%m-%d", float_format="%.0f")
    provenance = {"publisher": "Transport for London", "dataset": "Number of Bicycle Hires",
                  "source_url": SOURCE_URL, "source_page": SOURCE_PAGE, "licence": "Open Government Licence v2.0",
                  "licence_url": LICENCE_URL, "downloaded_on": "2026-10-05", "source_sha256": SOURCE_SHA256,
                  "source_bytes": path.stat().st_size, "processed_sha256": file_digest(destination), "quality": quality}
    (processed_dir / "provenance.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return provenance


def load_daily(project_dir: str | Path, verify: bool = True) -> pd.DataFrame:
    path = Path(project_dir) / "data" / "processed" / "daily.csv"
    if verify:
        provenance = json.loads(path.with_name("provenance.json").read_text(encoding="utf-8"))
        if file_digest(path) != provenance["processed_sha256"]:
            raise ValueError("The processed data checksum does not match its recorded provenance.")
    frame = pd.read_csv(path, parse_dates=["date"])
    if frame["date"].duplicated().any() or not frame["date"].is_monotonic_increasing:
        raise ValueError("The processed daily grain is invalid.")
    if not (frame["date"].diff().iloc[1:] == pd.Timedelta(days=1)).all():
        raise ValueError("The processed calendar must preserve missing dates as blank rows.")
    return frame
