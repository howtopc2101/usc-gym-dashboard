import os
from datetime import datetime

from flask import Flask, jsonify, send_from_directory, request
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

import tracker  # uses tracker.log_once() and DB helpers

# Live USC RecSports API
API_URL = (
    "https://goboardapi.azurewebsites.net/api/FacilityCount/"
    "GetCountsByAccount?AccountAPIKey=D2A34F88-54D5-472A-8325-8B3E15C1B5EE"
)

# Render / local DB URL (set in environment)
DATABASE_URL = os.environ.get("DATABASE_URL")

app = Flask(__name__, static_folder=".", static_url_path="")


def get_db_conn():
    """
    Basic Postgres connection helper.
    tracker.py can either use this or its own connection logic,
    but we keep this here in case you want to reuse it.
    """
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(DATABASE_URL, sslmode="require", cursor_factory=RealDictCursor)


@app.route("/")
def index():
    # Serve the dashboard UI
    return send_from_directory(".", "index.html")


@app.route("/api/live")
def api_live():
    """
    Proxy the live USC RecSports API.
    The front-end uses this to show current counts.
    """
    try:
        resp = requests.get(API_URL, timeout=5)
        resp.raise_for_status()
    except requests.RequestException as e:
        return jsonify({"error": "Failed to reach live API", "detail": str(e)}), 502

    try:
        data = resp.json()
    except Exception as e:
        return jsonify({"error": "Failed to parse live API JSON", "detail": str(e)}), 502

    return jsonify(data)


@app.route("/api/history")
def api_history():
    """
    Return historical data for one room (area), using your Postgres logs.

    Expected JSON shape (tracker.get_history_for_area should produce this):

    {
      "today_points": [
        {"timestamp": "...", "percent": 42},
        ...
      ],
      "baseline_hourly": [
        {"hour": 0, "avg_percent": 10},
        ...
      ],
      "heatmap": [
        {"dow": 0, "hours": [val0, val1, ...]},  # Monday
        ...
      ]
    }
    """
    area = request.args.get("area")
    if not area:
        return jsonify({"error": "Missing 'area' query parameter"}), 400

    try:
        data = tracker.get_history_for_area(area)
    except Exception as e:
        return jsonify({"error": "Failed to load history", "detail": str(e)}), 500

    return jsonify(data)


@app.route("/api/log", methods=["GET", "POST"])
def api_log():
    """
    One-shot logger endpoint.

    - Render Cron will hit GET /api/log every 15 minutes.
    - You can also POST manually if you want.
    """
    try:
        result = tracker.log_once()
    except Exception as e:
        return jsonify({"error": "log_once failed", "detail": str(e)}), 500

    # Optional: add a timestamp so you see when it ran
    result_with_time = {
        "ran_at": datetime.utcnow().isoformat() + "Z",
        **(result if isinstance(result, dict) else {"result": result}),
    }
    return jsonify(result_with_time)


# Optional: simple health check for Render
@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    # Local dev only. Render will use gunicorn.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
