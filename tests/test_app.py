"""Application contracts, bounded uploads and exported forecast reconciliation."""
import csv
from datetime import date, timedelta
import io
import json
from pathlib import Path

import pytest

from app import create_app, parse_history_text

ROOT = Path(__file__).resolve().parents[1]


def synthetic_csv(days=35):
    return "date,hires\n" + "\n".join(f"{date(2025, 1, 1) + timedelta(days=i)},{1000 + i}" for i in range(days))


def test_parser_preserves_dates_and_zero_counts():
    text = synthetic_csv().replace("2025-01-01,1000", "2025-01-01,0")
    rows = parse_history_text("\ufeff" + text)
    assert len(rows) == 35
    assert rows[0] == {"date": "2025-01-01", "hires": 0}
    assert rows[-1]["date"] == "2025-02-04"


@pytest.mark.parametrize("bad_count", ["-1", "1.5", "NaN", "inf", "1e100", "", "one thousand"])
def test_parser_rejects_unusable_counts(bad_count):
    with pytest.raises(ValueError):
        parse_history_text(synthetic_csv().replace("2025-01-01,1000", f"2025-01-01,{bad_count}"))


@pytest.mark.parametrize("bad_date", ["2025-02-30", "01/01/2025", "1500-01-01", "2200-01-01"])
def test_parser_rejects_invalid_or_ambiguous_dates(bad_date):
    with pytest.raises(ValueError):
        parse_history_text(synthetic_csv().replace("2025-01-01", bad_date))


def test_parser_rejects_missing_duplicate_or_reversed_days():
    for replacement in ("2025-01-01", "2025-01-03", "2024-12-31"):
        with pytest.raises(ValueError, match="consecutive"):
            parse_history_text(synthetic_csv().replace("2025-01-02", replacement))


def test_parser_requires_enough_history_and_bounded_inputs():
    for text in ("", "hires,value\n1,2", synthetic_csv(34), synthetic_csv(3001), " " * 500001, None):
        with pytest.raises(ValueError):
            parse_history_text(text)


@pytest.fixture
def client():
    app = create_app(ROOT)
    app.config["TESTING"] = True
    return app.test_client()


def test_app_and_source_backed_routes(client):
    assert client.get("/").status_code == 200
    assert client.get("/health").get_json()["status"] == "ready"
    summary = client.get("/api/summary").get_json()
    assert len(summary["models"]) == 4
    history = client.get("/api/history").get_json()["history"]
    assert len(history) == 5877
    assert history[-1]["date"] == "2026-08-31"
    assert client.get("/api/forecast?origin=not-a-date").status_code == 404
    assert client.get("/api/weeks/2020-01-01").status_code == 404


def test_forecast_csv_reconciles_with_json(client):
    forecast = client.get("/api/forecast").get_json()
    response = client.get("/api/download")
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.data.decode())))
    assert len(rows) == 7
    for exported, point in zip(rows, forecast["points"]):
        assert exported["date"] == point["date"]
        assert float(exported["prediction"]) == pytest.approx(point["prediction"])
        assert float(exported["lower"]) == pytest.approx(point["lower"])
        assert float(exported["upper"]) == pytest.approx(point["upper"])
        assert exported["actual"] in ("", "None")


def test_replay_is_an_actual_stored_forecast(client):
    weeks = client.get("/api/weeks").get_json()["weeks"]
    first = weeks[0]
    selected = client.get(f'/api/forecast?origin={first["origin"]}').get_json()
    assert selected == first
    assert len(selected["points"]) == 7
    assert all(point["actual"] >= 0 for point in selected["points"])
    assert client.get(f'/api/weeks/{first["origin"]}').get_json() == first


def test_valid_upload_matches_shipped_snapshot_without_truth(client):
    sample = client.get("/api/sample")
    assert sample.status_code == 200
    text = sample.data.decode()
    response = client.post("/api/predict", json={"text": text})
    assert response.status_code == 200, response.data
    uploaded = response.get_json()
    expected = client.get("/api/forecast").get_json()
    assert uploaded["origin"] == expected["origin"]
    assert len(uploaded["points"]) == 7
    for actual, target in zip(uploaded["points"], expected["points"]):
        assert actual["prediction"] == pytest.approx(target["prediction"], abs=0.011)
        assert "actual" not in actual
    assert uploaded["warnings"]


def test_upload_failure_responses_are_explanatory(client):
    assert client.post("/api/predict", data="not-json").status_code == 415
    for payload in ([1, 2], {"text": 12}, {"text": synthetic_csv().replace("1000", "1e100")}):
        response = client.post("/api/predict", json=payload)
        assert response.status_code == 400
        assert response.get_json()["error"]
    assert client.post("/api/predict", data="{broken", content_type="application/json").status_code == 400
    assert client.post("/api/predict", json={"text": "x" * 600001}).status_code == 413


@pytest.mark.parametrize("text", ["\ufeff", "date,hires\n2025-01-01," + "1" * 150000], ids=["empty-bom", "oversized-field"])
def test_empty_bom_and_oversized_csv_fields_return_validation_errors(client, text):
    response = client.post("/api/predict", json={"text": text})
    assert response.status_code == 400
    assert response.get_json()["error"]


def test_security_headers_and_uploads_are_not_saved(client):
    before = set(ROOT.rglob("*.csv"))
    response = client.post("/api/predict", json={"text": synthetic_csv()})
    assert response.status_code == 200
    assert set(ROOT.rglob("*.csv")) == before
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
