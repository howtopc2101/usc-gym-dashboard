import os
import csv
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request
import requests
import pandas as pd

# USC live API
USC_API_URL = (
    "https://goboardapi.azurewebsites.net/api/FacilityCount/"
    "GetCountsByAccount?AccountAPIKey=D2A34F88-54D5-472A-8325-8B3E15C1B5EE"
)

CSV_FILE = "usc_gym_counts.csv"

app = Flask(__name__, template_folder="templates", static_folder="static")


def ensure_csv_exists():
    """Create CSV file with headers if it does not exist yet."""
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "timestamp",
                    "village_cardio",
                    "village_strength",
                    "lyon_cardio",
                    "lyon_strength",
                    "hsc_cardio",
                ]
            )


ensure_csv_exists()


def parse_counts(api_data):
    """
    Take raw USC API JSON and reduce it to 5 numbers:
    - village_cardio
    - village_strength
    - lyon_cardio
    - lyon_strength
    - hsc_cardio
    """
    counts = {
        "village_cardio": 0,
        "village_strength": 0,
        "lyon_cardio": 0,
        "lyon_strength": 0,
        "hsc_cardio": 0,
    }

    if isinstance(api_data, list):
        facilities = api_data
    else:
        facilities = [api_data]

    for facility in facilities:
        name = (facility.get("FacilityName") or "").lower()
        location = (facility.get("LocationName") or "").lower()
        count = facility.get("LastCount") or 0

        # Village / UV
        if "village" in name or "village" in location or "uv" in name:
            if "cardio" in location:
                counts["village_cardio"] = count
            elif "strength" in location or "weight" in location:
                counts["village_strength"] = count
            else:
                if counts["village_cardio"] == 0:
                    counts["village_cardio"] = count

        # Lyon Center
        elif "lyon" in name or "lyons" in name or "lyon" in location:
            if "cardio" in location:
                counts["lyon_cardio"] = count
            elif "strength" in location or "weight" in location:
                counts["lyon_strength"] = count
            else:
                if counts["lyon_cardio"] == 0:
                    counts["lyon_cardio"] = count

        # HSC
        if "hsc" in name or "hsc" in location or "health sciences" in name:
            counts["hsc_cardio"] = count

    return counts


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/log", methods=["GET"])
def log_once():
    """
    When called (by you or cron-job.org), this:
    - fetches the live USC counts
    - parses them into the 5 areas
    - appends one row to usc_gym_counts.csv
    - returns JSON with the new row
    """
    try:
        resp = requests.get(USC_API_URL, timeout=10)
        resp.raise_for_status()
        api_data = resp.json()

        counts = parse_counts(api_data)
        ts = datetime.now(timezone.utc).isoformat()

        with open(CSV_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    ts,
                    counts["village_cardio"],
                    counts["village_strength"],
                    counts["lyon_cardio"],
                    counts["lyon_strength"],
                    counts["hsc_cardio"],
                ]
            )

        return jsonify({"status": "ok", "timestamp": ts, "counts": counts})
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/api/latest", methods=["GET"])
def latest():
    """
    Frontend uses this to get the most recent recorded snapshot.
    """
    try:
        if not os.path.exists(CSV_FILE):
            return jsonify({"error": "no data yet"}), 404

        df = pd.read_csv(CSV_FILE)
        if df.empty:
            return jsonify({"error": "no data yet"}), 404

        last = df.iloc[-1]

        data = {
            "timestamp": last["timestamp"],
            "rooms": {
                "village_cardio": int(last["village_cardio"]),
                "village_strength": int(last["village_strength"]),
                "lyon_cardio": int(last["lyon_cardio"]),
                "lyon_strength": int(last["lyon_strength"]),
                "hsc_cardio": int(last["hsc_cardio"]),
            },
        }
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": "failed to read csv", "detail": str(e)}), 500


@app.route("/api/history", methods=["GET"])
def history():
    """
    Return recent historical data points for charts.

    Query params:
      - limit: max number of rows (default 500)
    """
    try:
        if not os.path.exists(CSV_FILE):
            return jsonify({"error": "no data yet"}), 404

        limit = request.args.get("limit", default=500, type=int)
        df = pd.read_csv(CSV_FILE)

        if df.empty:
            return jsonify({"error": "no data yet"}), 404

        if limit > 0 and len(df) > limit:
            df = df.iloc[-limit:]

        points = []
        for _, row in df.iterrows():
            points.append(
                {
                    "timestamp": row["timestamp"],
                    "village_cardio": int(row["village_cardio"]),
                    "village_strength": int(row["village_strength"]),
                    "lyon_cardio": int(row["lyon_cardio"]),
                    "lyon_strength": int(row["lyon_strength"]),
                    "hsc_cardio": int(row["hsc_cardio"]),
                }
            )

        return jsonify({"points": points})
    except Exception as e:
        return jsonify({"error": "failed to read history", "detail": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=True)
