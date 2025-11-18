import os
from datetime import datetime

from flask import Flask, jsonify, send_from_directory
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

import tracker  # your logging + DB helper module

# Live USC RecSports API
API_URL = (
    "https://goboardapi.azurewebsites.net/api/FacilityCount/"
    "GetCountsByAccount?AccountAPIKey=D2A34F88-54D5-472A-8325-8B3E15C1B5EE"
)

# DB URL (set in environment on Render and locally)
DATABASE_URL = os.environ.get("DATABASE_URL")

app = Flask(__name__, static_folder=".", static_url_path="")


def get_db_conn():
    """
    Postgres connection helper.
    Not required by tracker.py if it uses its own logic,
    but here if you want it.
    """
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")

    # sslmode=require works for Render external URLs
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        cursor_factory=RealDictCursor,
    )


# ---------- Basic routes ----------

@app.route("/")
def index():
    # Serve index.html from project root
    return send_from_directory(".", "index.html")


@app.route("/health")
def health():
    # Simple health check for Render and for you
    return jsonify({"status": "ok"})


# ---------- Live facility data (no DB) ----------

@app.route("/api/live")
def api_live():
    """
    Proxy the live USC RecSports API, but:
    - simplify the fields
    - rename locations to more normal names
    """

    try:
        resp = requests.get(API_URL, timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return jsonify({"error": "live_fetch_failed", "detail": str(e)}), 502

    def friendly_name(raw_name: str) -> str:
        """
        Map USC internal names to something students understand.
        Adjust as you like.
        """
        name = raw_name

        # Village
        name = name.replace("UV Strength Landing", "Village Strength Area")
        name = name.replace("UV Cardio Landing", "Village Cardio Area")
        name = name.replace("UV Cardio Room", "Village Cardio Room")
        name = name.replace("UV Strength Room", "Village Strength Room")
        name = name.replace("UV Group Ex 1", "Village Group Studio 1")
        name = name.replace("UV Group Ex 2", "Village Group Studio 2")
        name = name.replace("UV Queenax", "Village Functional Rig")

        # Lyon Center
        name = name.replace("LRC Weight Room", "Lyon Weight Room")
        name = name.replace("LRC Functional Training Room", "Lyon Functional Room")
        name = name.replace("LRC Free Weights & Stretching", "Lyon Free Weights")
        name = name.replace("LRC Robinson Room", "Lyon Robinson Room")
        name = name.replace("LRC Main Gym Court A", "Lyon Court A")
        name = name.replace("LRC Main Gym Court B", "Lyon Court B")
        name = name.replace("LRC Main Gym Court C", "Lyon Court C")

        # Pools / HSC
        name = name.replace("UAC Comp Pool", "Uytengsu Competition Pool")
        name = name.replace("UAC Dive Pool - No Divers", "Dive Pool (no divers)")
        name = name.replace("UAC Dive Pool - Divers", "Dive Pool (with divers)")
        name = name.replace("PED Pool", "PED Pool")

        name = name.replace("HSC Cardio", "HSC Cardio")
        name = name.replace("HSC Strength Machines", "HSC Strength Machines")
        name = name.replace("HSC Weight Room", "HSC Weight Room")
        name = name.replace("HSC Small Group Ex", "HSC Small Group Ex")
        name = name.replace("HSC Large Group Ex", "HSC Large Group Ex")
        name = name.replace("HSC Basketball Court", "HSC Basketball Court")

        return name

    simplified = []
    for item in data:
        capacity = item.get("TotalCapacity") or 0
        count = item.get("LastCount") or 0
        percentage = 0
        if capacity > 0:
            percentage = round(100 * count / capacity)

        simplified.append(
            {
                "raw_name": item.get("LocationName"),
                "name": friendly_name(item.get("LocationName", "")),
                "facility": item.get("FacilityName"),
                "count": count,
                "capacity": capacity,
                "percent": percentage,
                "is_closed": bool(item.get("IsClosed")),
                "last_updated": item.get("LastUpdatedDateAndTime"),
            }
        )

    return jsonify({"as_of": datetime.utcnow().isoformat() + "Z", "locations": simplified})


# ---------- Logging route used by cron-job.org ----------

@app.route("/api/log", methods=["GET"])
def api_log():
    """
    Called every 15 minutes (cron-job.org).
    Uses tracker.log_once() to:
    - pull live data
    - insert a snapshot into Postgres
    Returns a JSON summary for debugging.
    """

    # tracker.log_once() should handle:
    # - connecting to DB (using DATABASE_URL)
    # - calling the live API
    # - writing rows
    try:
        result = tracker.log_once()
    except Exception as e:
        return jsonify({"error": "log_once_failed", "detail": str(e)}), 500

    payload = {
        "ran_at": datetime.utcnow().isoformat() + "Z",
    }

    if isinstance(result, dict):
        payload.update(result)
    else:
        payload["result"] = str(result)

    return jsonify(payload)


if __name__ == "__main__":
    # Local dev entrypoint. Render uses `gunicorn app:app` instead.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
