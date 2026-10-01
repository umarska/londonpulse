"""LondonPulse's local research app and bounded, in-memory forecasting API."""
from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from functools import lru_cache
import io
import json
import math
from pathlib import Path
import re
import sys

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR / "src"))
MAX_ROWS = 3000
MAX_TEXT_BYTES = 500_000


def parse_history_text(text: str) -> list[dict]:
    """Validate a chronological date/hires CSV without guessing missing days."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Choose a non-empty CSV with date and hires columns.")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("Choose a CSV smaller than 500 kB.")
    lines = [line for line in text.lstrip("\ufeff").splitlines() if line.strip()]
    if not lines:
        raise ValueError("Choose a non-empty CSV with date and hires columns.")
    if len(lines) > MAX_ROWS + 1:
        raise ValueError("Upload at most 3,000 daily observations.")
    try:
        records = list(csv.reader(lines))
    except csv.Error as exc:
        raise ValueError("The CSV contains an oversized or malformed field. Use the date and hires columns in the sample.") from exc
    header = [cell.strip().lower() for cell in records[0]]
    if len(header) != 2 or set(header) != {"date", "hires"}:
        raise ValueError("Use exactly two columns: date (YYYY-MM-DD) and hires (a whole-number daily count).")
    if len(records) - 1 < 35:
        raise ValueError("Include at least 35 consecutive daily observations.")
    rows = []
    previous = None
    for row_number, values in enumerate(records[1:], start=2):
        if len(values) != 2:
            raise ValueError(f"Row {row_number} must have exactly two columns.")
        record = dict(zip(header, (value.strip() for value in values)))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["date"]):
            raise ValueError(f"Row {row_number}: use dates in YYYY-MM-DD format.")
        try:
            observed_date = date.fromisoformat(record["date"])
        except ValueError as exc:
            raise ValueError(f"Row {row_number} contains an invalid calendar date.") from exc
        if not 1900 <= observed_date.year <= 2100:
            raise ValueError(f"Row {row_number}: dates must fall between 1900 and 2100.")
        if previous is not None and observed_date != previous + timedelta(days=1):
            raise ValueError(f"Row {row_number}: dates must be unique, consecutive and in chronological order. Do not fill missing counts with zero.")
        try:
            count = float(record["hires"])
        except ValueError as exc:
            raise ValueError(f"Row {row_number}: hires must be a non-negative whole number.") from exc
        if not math.isfinite(count) or not 0 <= count <= 100_000_000 or not count.is_integer():
            raise ValueError(f"Row {row_number}: hires must be a whole number between 0 and 100,000,000.")
        rows.append({"date": observed_date.isoformat(), "hires": int(count)})
        previous = observed_date
    return rows


def create_app(project_dir: Path | None = None) -> Flask:
    root = Path(project_dir or PROJECT_DIR).resolve()
    app = Flask(__name__, static_folder=str(root / "static"))
    app.config.update(MAX_CONTENT_LENGTH=600_000, JSON_SORT_KEYS=False)

    @lru_cache(maxsize=1)
    def demo():
        return json.loads((root / "artifacts" / "demo.json").read_text(encoding="utf-8"))

    @lru_cache(maxsize=1)
    def predictor():
        from londonpulse.inference import ForecastPredictor
        return ForecastPredictor.from_artifacts(root)

    def forecast_at_origin(origin):
        if not origin:
            return demo()["next_forecast"]
        if origin == demo()["next_forecast"]["origin"]:
            return demo()["next_forecast"]
        return next((week for week in demo()["weeks"] if week["origin"] == origin), None)

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        return response

    @app.get("/")
    def index():
        return send_from_directory(root / "static", "index.html")

    @app.get("/health")
    def health():
        ready = (root / "artifacts" / "demo.json").exists() and (root / "models" / "model.joblib").exists()
        return jsonify(project="LondonPulse", status="ready" if ready else "missing_artifacts"), 200 if ready else 503

    @app.get("/api/summary")
    def summary():
        data = demo()
        return jsonify({key: data[key] for key in ("metadata", "overview", "models", "diagnostics", "next_forecast")})

    @app.get("/api/history")
    def history():
        return jsonify(history=demo()["history"])

    @app.get("/api/weeks")
    def weeks():
        return jsonify(weeks=demo()["weeks"])

    @app.get("/api/weeks/<origin>")
    def week(origin):
        result = next((item for item in demo()["weeks"] if item["origin"] == origin), None)
        if result is None:
            return jsonify(error="Choose a forecast origin from the available backtest weeks."), 404
        return jsonify(result)

    @app.get("/api/forecast")
    def forecast():
        result = forecast_at_origin(request.args.get("origin"))
        if result is None:
            return jsonify(error="That forecast origin is unavailable. Choose a date from the replay list."), 404
        return jsonify(result)

    @app.get("/api/download")
    def download():
        result = forecast_at_origin(request.args.get("origin"))
        if result is None:
            return jsonify(error="Forecast not found."), 404
        columns = ["origin", "date", "horizon", "prediction", "lower", "upper", "actual", "seasonal_naive", "weekday_mean", "ridge"]
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for point in result["points"]:
            writer.writerow({**point, "origin": result["origin"]})
        return Response(buffer.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="londonpulse-{result["origin"]}.csv"'})

    @app.get("/api/sample")
    def sample():
        return send_from_directory(root / "data" / "examples", "sample.csv", as_attachment=True, download_name="londonpulse-sample.csv")

    @app.post("/api/predict")
    def predict():
        if not request.is_json:
            return jsonify(error="Send a JSON object containing the CSV as text."), 415
        payload = request.get_json()
        if not isinstance(payload, dict):
            return jsonify(error="Send a JSON object containing the CSV as text."), 400
        try:
            rows = parse_history_text(payload.get("text"))
            from threadpoolctl import threadpool_limits
            with threadpool_limits(limits=2):
                result = predictor().forecast(rows, days=7)
            result["label"] = "Uploaded London cycle hire history"
            for point in result["points"]:
                point.pop("actual", None)
            result.setdefault("warnings", []).append("This model was fitted to aggregate London cycle hires. Its historical calibration ranges may not apply to uploaded data or another scheme.")
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(result)

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_):
        return jsonify(error="The upload is too large. Choose a CSV smaller than 500 kB."), 413

    @app.errorhandler(BadRequest)
    def bad_request(_):
        return jsonify(error="The request contains invalid JSON."), 400

    @app.errorhandler(FileNotFoundError)
    def missing_artifacts(_):
        return jsonify(error="The model artefacts are missing. Run python -m londonpulse.train from the project folder."), 503

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the LondonPulse research app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5051)
    arguments = parser.parse_args()
    print(f"LondonPulse: http://{arguments.host}:{arguments.port}")
    create_app().run(host=arguments.host, port=arguments.port, debug=False)
