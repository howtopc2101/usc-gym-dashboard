import os
import requests
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values

API_URL = "https://goboardapi.azurewebsites.net/api/FacilityCount/GetCountsByAccount?AccountAPIKey=D2A34F88-54D5-472A-8325-8B3E15C1B5EE"

# Render will set this environment variable. Locally you can set it too if you want to test DB.
DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable not set")
    # Render Postgres usually needs SSL
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def ensure_table_exists():
    ddl = """
    CREATE TABLE IF NOT EXISTS gym_readings (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL,
        location_name TEXT NOT NULL,
        count INTEGER,
        capacity INTEGER,
        percent REAL
    );
    """
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
    finally:
        conn.close()


def get_locations():
    """Fetch live API and normalize into list of dicts."""
    r = requests.get(API_URL)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise ValueError("Unexpected API response structure (expected list)")

    locations = []
    for loc in data:
        name = loc.get("LocationName", "Unknown")
        capacity = loc.get("TotalCapacity")
        count = loc.get("LastCount")
        if count is None:
            count = loc.get("CountOfParticipants")

        percent = loc.get("PercetageCapacity")
        if (percent is None or percent == 0) and count is not None and capacity not in (None, 0):
            try:
                percent = round(100 * float(count) / float(capacity), 1)
            except Exception:
                percent = None

        locations.append(
            {
                "name": str(name),
                "count": count,
                "capacity": capacity,
                "percent": percent,
            }
        )
    return locations


def log_once():
    """
    Fetch live data once and insert one row per location into Postgres.
    """
    ensure_table_exists()
    locations = get_locations()
    ts = datetime.utcnow()  # single timestamp for this batch

    rows = []
    for loc in locations:
        rows.append(
            (
                ts,
                loc["name"],
                loc["count"],
                loc["capacity"],
                loc["percent"],
            )
        )

    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """
                    INSERT INTO gym_readings (ts, location_name, count, capacity, percent)
                    VALUES %s
                    """,
                    rows,
                )
    finally:
        conn.close()


if __name__ == "__main__":
    # Local test requires DATABASE_URL set and reachable Postgres.
    log_once()
    print("Logged one batch of rows into Postgres.")
