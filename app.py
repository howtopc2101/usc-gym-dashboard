import os
import requests
from datetime import datetime, date
from collections import defaultdict

from flask import Flask, jsonify, send_from_directory, request

import psycopg2
from psycopg2.extras import RealDictCursor

import tracker  # uses tracker.log_once() and DB helpers

API_URL = "https://goboardapi.azurewebsites.net/api/FacilityCount/GetCountsByAccount?AccountAPIKey=D2A34F88-54D5-472A-8325-8B3E15C1B5EE"
DATABASE_URL = os.environ.get("DATABASE_URL")

app = Flask(__name__)


def get_db_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable not set")
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def parse_timestamp(ts_obj):
    if isinstance(ts_obj, datetime):
        return ts_obj
    if isinstance(ts_obj, str):
        try:
            return datetime.fromisoformat(ts_obj)
        except Exception:
            return None
    return None


def load_area_series(area_name):
    """
    Load (timestamp, percent) tuples for a given area from Postgres.
    """
    conn = get_db_conn()
    rows = []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT ts, percent
                    FROM gym_readings
                    WHERE location_name = %s
                    ORDER BY ts ASC
                    """,
                    (area_name,),
                )
                for rec in cur.fetchall():
                    ts = parse_timestamp(rec["ts"])
                    pct = rec["percent"]
                    if ts is None or pct is None:
                        continue
                    try:
                        pct_val = float(pct)
                    except Exception:
                        continue
                    rows.append((ts, pct_val))
    finally:
        conn.close()

    return rows


def build_trend_data(area_name, days_for_baseline=14, max_recent=300):
    series = load_area_series(area_name)
    if not series:
        return {
            "recent_points": [],
            "today_points": [],
            "baseline_hourly": [],
            "heatmap": [],
        }

    series.sort(key=lambda x: x[0])

    today = date.today()
    cutoff = today.toordinal() - days_for_baseline

    hourly_sum = defaultdict(float)
    hourly_count = defaultdict(int)

    heatmap_sum = defaultdict(float)
    heatmap_count = defaultdict(int)

    recent_points = []
    today_points = []

    for ts, pct in series:
        recent_points.append({"timestamp": ts.isoformat(), "percent": pct})
        d = ts.date()
        dow = ts.weekday()
        hour = ts.hour
        ord_day = d.toordinal()

        if d == today:
            today_points.append({"timestamp": ts.isoformat(), "percent": pct})

        if ord_day >= cutoff:
            hourly_sum[hour] += pct
            hourly_count[hour] += 1
            heatmap_sum[(dow, hour)] += pct
            heatmap_count[(dow, hour)] += 1

    recent_points = recent_points[-max_recent:]

    baseline_hourly = []
    for hour in range(24):
        if hourly_count[hour]:
            avg = hourly_sum[hour] / hourly_count[hour]
            baseline_hourly.append({"hour": hour, "avg_percent": round(avg, 1)})
        else:
            baseline_hourly.append({"hour": hour, "avg_percent": None})

    heatmap = []
    for dow in range(7):
        row = {"dow": dow, "hours": []}
        for hour in range(24):
            key = (dow, hour)
            if heatmap_count[key]:
                avg = heatmap_sum[key] / heatmap_count[key]
                row["hours"].append(round(avg, 1))
            else:
                row["hours"].append(None)
        heatmap.append(row)

    return {
        "recent_points": recent_points,
        "today_points": today_points,
        "baseline_hourly": baseline_hourly,
        "heatmap": heatmap,
    }


@app.get("/api/live")
def api_live():
    r = requests.get(API_URL)
    r.raise_for_status()
    return jsonify(r.json())


@app.get("/api/history")
def api_history():
    area = request.args.get("area", "UV Cardio Landing")
    data = build_trend_data(area)
    return jsonify({"area": area, **data})


@app.post("/api/log")
def api_log():
    """
    Trigger one logging run: fetch live counts and insert rows to Postgres.
    Called by the scheduler every 15 minutes.
    """
    tracker.log_once()
    return jsonify({"status": "ok"})


@app.get("/")
def index():
    return send_from_directory(".", "index.html")


@app.get("/<path:path>")
def static_files(path):
    return send_from_directory(".", path)


if __name__ == "__main__":
    app.run(debug=True)
