import os
from datetime import datetime, timezone
from typing import List, Dict

import requests
import psycopg2
from psycopg2.extras import RealDictCursor

# Live USC RecSports API
API_URL = (
    "https://goboardapi.azurewebsites.net/api/FacilityCount/"
    "GetCountsByAccount?AccountAPIKey=D2A34F88-54D5-472A-8325-8B3E15C1B5EE"
)

DATABASE_URL = os.environ.get("DATABASE_URL")


# ---------- DB helpers ----------

def get_db_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        cursor_factory=RealDictCursor,
    )


def init_db():
    """Create table if it doesn't exist."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gym_samples (
                        id SERIAL PRIMARY KEY,
                        ts_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        area TEXT NOT NULL,
                        location_name TEXT NOT NULL,
                        count INTEGER NOT NULL,
                        capacity INTEGER NOT NULL,
                        percent REAL NOT NULL
                    );
                    """
                )
    finally:
        conn.close()


# ---------- Mapping helpers ----------

# Map raw facility names into “friendly” areas users understand.
FRIENDLY_AREAS = {
    "Village Strength Area": [
        "UV Strength Landing",
        "UV Strength Room",
    ],
    "Village Cardio Area": [
        "UV Cardio Landing",
        "UV Cardio Room",
    ],
    "Lyon Weight Rooms": [
        "LRC Weight Room",
        "LRC Functional Training Room",
        "LRC Free Weights & Stretching",
    ],
    "Lyon Courts": [
        "LRC Main Gym Court A",
        "LRC Main Gym Court B",
        "LRC Main Gym Court C",
    ],
    "HSC Cardio": [
        "HSC Cardio",
    ],
    "HSC Weights": [
        "HSC Strength Machines",
        "HSC Weight Room",
    ],
    "Aquatics": [
        "UAC Comp Pool",
        "PED Pool",
        "UAC Dive Pool - No Divers",
        "UAC Dive Pool - Divers",
    ],
}


def aggregate_live(data: List[Dict]) -> Dict[str, Dict]:
    """
    Take raw USC API list and aggregate into our friendly areas.
    Returns: { friendly_label: {count, capacity, percent} }
    """
    # Index raw by LocationName
    by_name = {item["LocationName"]: item for item in data}

    result = {}
    for friendly, raw_names in FRIENDLY_AREAS.items():
        total_count = 0
        total_capacity = 0

        for rn in raw_names:
            item = by_name.get(rn)
            if not item:
                continue
            total_count += item.get("CountOfParticipants", 0)
            total_capacity += item.get("TotalCapacity", 0)

        if total_capacity > 0:
            percent = round((total_count / total_capacity) * 100, 1)
        else:
            percent = 0.0

        result[friendly] = {
            "area": friendly,
            "count": total_count,
            "capacity": total_capacity,
            "percent": percent,
        }

    return result


# ---------- Logging ----------

def fetch_live_raw() -> List[Dict]:
    resp = requests.get(API_URL, timeout=10)
    resp.raise_for_status()
    return resp.json()


def log_once() -> Dict:
    """
    Fetch current counts from USC API, aggregate to friendly areas,
    and insert one row per area into gym_samples.
    """
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set; cannot log.")

    init_db()

    raw = fetch_live_raw()
    aggregated = aggregate_live(raw)

    conn = get_db_conn()
    inserted = 0
    now_utc = datetime.now(timezone.utc)

    try:
        with conn:
            with conn.cursor() as cur:
                for area_label, payload in aggregated.items():
                    cur.execute(
                        """
                        INSERT INTO gym_samples
                            (ts_utc, area, location_name, count, capacity, percent)
                        VALUES
                            (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            now_utc,
                            area_label,
                            area_label,  # store same label as location_name for now
                            payload["count"],
                            payload["capacity"],
                            payload["percent"],
                        ),
                    )
                    inserted += 1
    finally:
        conn.close()

    return {
        "ran_at": now_utc.isoformat(),
        "rows_inserted": inserted,
    }


def get_history(area: str, hours: int = 24) -> List[Dict]:
    """
    Return last `hours` of samples for the given friendly area.
    """
    init_db()
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        ts_utc,
                        count,
                        capacity,
                        percent
                    FROM gym_samples
                    WHERE area = %s
                      AND ts_utc >= NOW() - (%s || ' hours')::INTERVAL
                    ORDER BY ts_utc ASC;
                    """,
                    (area, str(hours)),
                )
                rows = cur.fetchall()
                # Convert datetime to ISO string for JSON
                for r in rows:
                    if isinstance(r["ts_utc"], datetime):
                        r["ts_utc"] = r["ts_utc"].isoformat()
                return rows
    finally:
        conn.close()
