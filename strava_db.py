#!/usr/bin/env python3
"""
strava_db.py  –  Build and maintain a local SQLite metadata database of
                 your Strava activities.

MODES
-----
  build-archive   Build the database from a Strava bulk-export archive ZIP.
                  Usage: python strava_db.py build-archive <path/to/export.zip>

  build-api       Pull every activity from the API (slow – respects rate limits).
                  Usage: python strava_db.py build-api

  update          Pull only activities newer than the most-recent one in the DB,
                  then re-verify the last ~30 days already stored.
                  Usage: python strava_db.py update

QUERIES (convenience)
---------------------
  stats           Print a quick summary to stdout.
                  Usage: python strava_db.py stats

  backfill-detail Fetch the full detail endpoint for activities that are
                  missing workout_type (race / long run / workout flag).
                  Safe to interrupt and re-run — skips already-filled rows.
                  Use --sport-types Run Ride to limit scope.
                  NOTE: costs 1 req/activity; at the Read limit of
                  1 000 req/day, 9 000 activities takes ~9 days.
                  See GitHub issue #2.
                  Usage: python strava_db.py backfill-detail [--sport-types Run Ride]

RATE LIMITS
-----------
  Strava API rate limits (as of 2026):
    Overall : 200 requests / 15 min,  2 000 requests / day
    Read    : 100 requests / 15 min,  1 000 requests / day

  This script only makes read requests, so the tighter Read limits apply.
  The script sleeps automatically when it approaches the short-term limit.

ENV / .env
----------
  STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET,
  STRAVA_ACCESS_TOKEN, STRAVA_REFRESH_TOKEN,
  DB_PATH  (default: strava.db)
"""

import argparse
import csv
import io
import os
import re
import sqlite3
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv, set_key


def write_dotenv_tokens(access: str, refresh: str, path: Path = Path(".env")) -> None:
    """Persist refreshed tokens back into the .env file."""
    set_key(str(path), "STRAVA_ACCESS_TOKEN",  access)
    set_key(str(path), "STRAVA_REFRESH_TOKEN", refresh)


# ---------------------------------------------------------------------------
# Strava OAuth helper
# ---------------------------------------------------------------------------

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE  = "https://www.strava.com/api/v3"

# Short-term: 100 req / 15 min.  We back off at 90 to stay safe.
_SHORT_TERM_LIMIT = 90
_SHORT_TERM_WINDOW_SECS = 15 * 60  # 15 minutes

_request_times: list[float] = []   # timestamps of recent requests


def _record_request() -> None:
    now = time.monotonic()
    _request_times.append(now)
    # Drop entries older than the window
    cutoff = now - _SHORT_TERM_WINDOW_SECS
    while _request_times and _request_times[0] < cutoff:
        _request_times.pop(0)


def _maybe_sleep() -> None:
    """Sleep if we're close to the short-term rate limit."""
    if len(_request_times) >= _SHORT_TERM_LIMIT:
        oldest = _request_times[0]
        sleep_for = _SHORT_TERM_WINDOW_SECS - (time.monotonic() - oldest) + 2
        if sleep_for > 0:
            print(f"  [rate-limit] sleeping {sleep_for:.0f}s …", flush=True)
            time.sleep(sleep_for)
            # Clear stale entries
            cutoff = time.monotonic() - _SHORT_TERM_WINDOW_SECS
            while _request_times and _request_times[0] < cutoff:
                _request_times.pop(0)


class StravaClient:
    def __init__(self, client_id: str, client_secret: str,
                 access_token: str, refresh_token: str,
                 env_path: Path = Path(".env")):
        self.client_id     = client_id
        self.client_secret = client_secret
        self.access_token  = access_token
        self.refresh_token = refresh_token
        self.env_path      = env_path
        self.session       = requests.Session()

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        print("  [auth] refreshing access token …", flush=True)
        resp = self.session.post(STRAVA_TOKEN_URL, data={
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
            "grant_type":    "refresh_token",
            "refresh_token": self.refresh_token,
        })
        resp.raise_for_status()
        data = resp.json()
        self.access_token  = data["access_token"]
        self.refresh_token = data["refresh_token"]
        write_dotenv_tokens(self.access_token, self.refresh_token, self.env_path)
        print("  [auth] tokens updated.", flush=True)

    def _get(self, path: str, params: Optional[dict] = None,
             retry: bool = True) -> Any:
        _maybe_sleep()
        url = f"{STRAVA_API_BASE}{path}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        resp = self.session.get(url, headers=headers, params=params or {})
        _record_request()

        if resp.status_code == 401 and retry:
            self._refresh()
            return self._get(path, params, retry=False)

        if resp.status_code == 429:
            # Hard rate-limit hit – back off for the full window
            print("  [rate-limit] 429 received – sleeping 15 min …", flush=True)
            time.sleep(_SHORT_TERM_WINDOW_SECS + 5)
            return self._get(path, params, retry=False)

        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def get_athlete(self) -> dict:
        return self._get("/athlete")

    def list_activities(self, page: int = 1, per_page: int = 100,
                        after: Optional[int] = None,
                        before: Optional[int] = None) -> list[dict]:
        params: dict = {"page": page, "per_page": per_page}
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before
        return self._get("/athlete/activities", params=params)

    def iter_all_activities(self, after: Optional[int] = None,
                            before: Optional[int] = None):
        """Yield every activity summary, handling pagination."""
        page = 1
        total = 0
        while True:
            batch = self.list_activities(page=page, per_page=100,
                                         after=after, before=before)
            if not batch:
                break
            for act in batch:
                yield act
                total += 1
            print(f"  fetched page {page} ({len(batch)} activities, "
                  f"{total} total) …", flush=True)
            page += 1
            if len(batch) < 100:
                break


# ---------------------------------------------------------------------------
# Schema & DB helpers
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id                  INTEGER PRIMARY KEY,
    name                TEXT,
    sport_type          TEXT,   -- e.g. Ride, Run, Walk, Swim …
    type                TEXT,   -- legacy field kept for compat
    start_date          TEXT,   -- ISO-8601 UTC
    start_date_local    TEXT,   -- ISO-8601 local time
    timezone            TEXT,
    distance_m          REAL,   -- metres
    moving_time_s       INTEGER,-- seconds
    elapsed_time_s      INTEGER,-- seconds
    total_elevation_m   REAL,   -- metres
    average_speed_ms    REAL,   -- m/s
    max_speed_ms        REAL,
    average_heartrate   REAL,
    max_heartrate       REAL,
    average_watts       REAL,
    device_watts        INTEGER,-- boolean
    average_cadence     REAL,
    suffer_score        REAL,
    calories            REAL,
    gear_id             TEXT,
    gear_name           TEXT,
    commute             INTEGER,-- boolean
    trainer             INTEGER,-- boolean
    manual              INTEGER,-- boolean
    flagged             INTEGER,-- boolean
    visibility          TEXT,
    map_summary_polyline TEXT,
    achievement_count   INTEGER,
    kudos_count         INTEGER,
    comment_count       INTEGER,
    athlete_count       INTEGER,
    photo_count         INTEGER,
    pr_count            INTEGER,
    workout_type        INTEGER,-- 0=default,1=race,2=long run,3=workout (run)
                                -- 10=default,11=race,12=workout (ride); NULL=unknown
    source              TEXT,   -- "archive" | "api"
    fetched_at          TEXT    -- ISO-8601 UTC when we wrote this row
);

CREATE TABLE IF NOT EXISTS gear (
    id      TEXT PRIMARY KEY,
    name    TEXT,
    brand   TEXT,
    model   TEXT,
    distance_m REAL
);

CREATE TABLE IF NOT EXISTS meta (
    key     TEXT PRIMARY KEY,
    value   TEXT
);
"""

def open_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.commit()
    return con


def upsert_activity(con: sqlite3.Connection, row: dict) -> None:
    cols = list(row.keys())
    placeholders = ", ".join("?" * len(cols))
    col_names = ", ".join(cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    sql = (f"INSERT INTO activities ({col_names}) VALUES ({placeholders}) "
           f"ON CONFLICT(id) DO UPDATE SET {updates}")
    con.execute(sql, list(row.values()))


def upsert_gear(con: sqlite3.Connection, row: dict) -> None:
    con.execute(
        "INSERT INTO gear (id, name, brand, model, distance_m) "
        "VALUES (:id, :name, :brand, :model, :distance_m) "
        "ON CONFLICT(id) DO UPDATE SET "
        "  name=excluded.name, brand=excluded.brand, "
        "  model=excluded.model, distance_m=excluded.distance_m",
        row)


def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value))


def get_meta(con: sqlite3.Connection, key: str) -> Optional[str]:
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Activity dict → DB row
# ---------------------------------------------------------------------------

def _s(d: dict, *keys):
    """Safely fetch a nested value from a dict."""
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def activity_to_row(act: dict, source: str = "api") -> dict:
    return {
        "id":                   act.get("id"),
        "name":                 act.get("name"),
        "sport_type":           act.get("sport_type") or act.get("type"),
        "type":                 act.get("type"),
        "start_date":           act.get("start_date"),
        "start_date_local":     act.get("start_date_local"),
        "timezone":             act.get("timezone"),
        "distance_m":           act.get("distance"),
        "moving_time_s":        act.get("moving_time"),
        "elapsed_time_s":       act.get("elapsed_time"),
        "total_elevation_m":    act.get("total_elevation_gain"),
        "average_speed_ms":     act.get("average_speed"),
        "max_speed_ms":         act.get("max_speed"),
        "average_heartrate":    act.get("average_heartrate"),
        "max_heartrate":        act.get("max_heartrate"),
        "average_watts":        act.get("average_watts"),
        "device_watts":         int(bool(act.get("device_watts"))),
        "average_cadence":      act.get("average_cadence"),
        "suffer_score":         act.get("suffer_score"),
        "calories":             act.get("calories"),
        "gear_id":              act.get("gear_id"),
        "gear_name":            _s(act, "gear", "name"),
        "commute":              int(bool(act.get("commute"))),
        "trainer":              int(bool(act.get("trainer"))),
        "manual":               int(bool(act.get("manual"))),
        "flagged":              int(bool(act.get("flagged"))),
        "visibility":           act.get("visibility"),
        "map_summary_polyline": _s(act, "map", "summary_polyline"),
        "achievement_count":    act.get("achievement_count"),
        "kudos_count":          act.get("kudos_count"),
        "comment_count":        act.get("comment_count"),
        "athlete_count":        act.get("athlete_count"),
        "photo_count":          act.get("total_photo_count"),
        "pr_count":             act.get("pr_count"),
        "workout_type":         act.get("workout_type"),  # None from summary; int from detail
        "source":               source,
        "fetched_at":           now_utc(),
    }


# ---------------------------------------------------------------------------
# Archive (ZIP) import
# ---------------------------------------------------------------------------

def import_archive(zip_path: str, db_path: str) -> None:
    """
    Import activities from a Strava bulk-export ZIP.

    The archive contains:
      activities.csv          – one row per activity (summary metadata)
      activities/<id>.gpx     – optional GPS tracks (we skip these)
    """
    print(f"Opening archive: {zip_path}", flush=True)
    con = open_db(db_path)
    count = 0

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

        # --- activities.csv ---
        csv_names = [n for n in names if n.lower().endswith("activities.csv")]
        if not csv_names:
            sys.exit("ERROR: No activities.csv found in the archive.")
        csv_name = csv_names[0]
        print(f"  Parsing {csv_name} …", flush=True)

        with zf.open(csv_name) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig")
            reader = csv.DictReader(text)
            for csv_row in reader:
                row = _csv_row_to_db(csv_row)
                if row["id"] is None:
                    continue
                upsert_activity(con, row)
                count += 1
                if count % 500 == 0:
                    print(f"  … {count} activities imported", flush=True)

        con.commit()
        set_meta(con, "last_archive_import", now_utc())
        set_meta(con, "source", "archive")
        con.commit()

    print(f"Done. Imported {count} activities from archive → {db_path}")


def _csv_row_to_db(r: dict) -> dict:
    """Map a Strava export CSV row to our DB schema."""

    def _float(v):
        try:
            return float(v) if v not in (None, "", "—") else None
        except (TypeError, ValueError):
            return None

    def _int(v):
        try:
            return int(v) if v not in (None, "", "—") else None
        except (TypeError, ValueError):
            return None

    def _bool(v):
        return 1 if str(v).strip().lower() in ("true", "1", "yes") else 0

    # The CSV uses column names like "Activity ID", "Activity Name", etc.
    # Map the known columns; anything else is ignored.
    act_id   = _int(r.get("Activity ID") or r.get("id"))
    dist_raw = _float(r.get("Distance") or r.get("distance"))          # km in CSV
    # Moving/elapsed times are stored as "H:MM:SS" strings in the archive
    moving   = _hms_to_seconds(r.get("Moving Time") or r.get("moving_time", ""))
    elapsed  = _hms_to_seconds(r.get("Elapsed Time") or r.get("elapsed_time", ""))
    # Elevation: metres
    elev_raw = _float(r.get("Elevation Gain") or r.get("total_elevation_gain"))

    return {
        "id":                   act_id,
        "name":                 r.get("Activity Name") or r.get("name"),
        "sport_type":           r.get("Activity Type") or r.get("sport_type") or r.get("type"),
        "type":                 r.get("Activity Type") or r.get("type"),
        "start_date":           _iso(r.get("Activity Date") or r.get("start_date")),
        "start_date_local":     _iso(r.get("Activity Date") or r.get("start_date_local")),
        "timezone":             r.get("timezone"),
        "distance_m":           dist_raw * 1000 if dist_raw is not None else None,
        "moving_time_s":        moving,
        "elapsed_time_s":       elapsed,
        "total_elevation_m":    elev_raw,
        "average_speed_ms":     _float(r.get("Average Speed") or r.get("average_speed")),
        "max_speed_ms":         _float(r.get("Max Speed")     or r.get("max_speed")),
        "average_heartrate":    _float(r.get("Average Heart Rate") or r.get("average_heartrate")),
        "max_heartrate":        _float(r.get("Max Heart Rate")     or r.get("max_heartrate")),
        "average_watts":        _float(r.get("Average Watts")      or r.get("average_watts")),
        "device_watts":         _bool(r.get("device_watts", 0)),
        "average_cadence":      _float(r.get("Average Cadence")    or r.get("average_cadence")),
        "suffer_score":         _float(r.get("Relative Effort")    or r.get("suffer_score")),
        "calories":             _float(r.get("Calories")           or r.get("calories")),
        "gear_id":              r.get("gear_id"),
        "gear_name":            r.get("Gear") or r.get("gear_name"),
        "commute":              _bool(r.get("Commute") or r.get("commute", 0)),
        "trainer":              _bool(r.get("trainer", 0)),
        "manual":               _bool(r.get("manual", 0)),
        "flagged":              _bool(r.get("flagged", 0)),
        "visibility":           r.get("visibility"),
        "map_summary_polyline": r.get("map_summary_polyline"),
        "achievement_count":    _int(r.get("achievement_count")),
        "kudos_count":          _int(r.get("kudos_count")),
        "comment_count":        _int(r.get("comment_count")),
        "athlete_count":        _int(r.get("athlete_count")),
        "photo_count":          _int(r.get("photo_count")),
        "pr_count":             _int(r.get("pr_count")),
        "source":               "archive",
        "fetched_at":           now_utc(),
    }


def _hms_to_seconds(v: str) -> Optional[int]:
    """Convert 'H:MM:SS' or 'MM:SS' or bare seconds to int seconds."""
    if not v:
        return None
    v = str(v).strip()
    # Already an integer string?
    try:
        return int(v)
    except ValueError:
        pass
    parts = v.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        pass
    return None


def _iso(v: str) -> Optional[str]:
    """Best-effort parse of various date strings to ISO-8601."""
    if not v:
        return None
    # Already ISO
    if re.match(r"\d{4}-\d{2}-\d{2}T", v):
        return v
    # "Mar 15, 2025, 7:30:00 AM" (Strava export format)
    for fmt in (
        "%b %d, %Y, %I:%M:%S %p",
        "%b %d, %Y, %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(v, fmt).isoformat()
        except ValueError:
            pass
    return v  # pass through as-is


# ---------------------------------------------------------------------------
# API import
# ---------------------------------------------------------------------------

def build_from_api(client: StravaClient, con: sqlite3.Connection,
                   after: Optional[int] = None) -> int:
    """Fetch all (or post-`after`) activities from the API. Returns count."""
    count = 0
    for act in client.iter_all_activities(after=after):
        row = activity_to_row(act, source="api")
        upsert_activity(con, row)
        count += 1
        if count % 50 == 0:
            con.commit()
    con.commit()
    return count


def do_build_api(client: StravaClient, db_path: str) -> None:
    con = open_db(db_path)
    print("Pulling all activities from Strava API …", flush=True)
    print("(This may take a long time and will pause for rate limits.)\n",
          flush=True)
    n = build_from_api(client, con)
    set_meta(con, "last_full_pull", now_utc())
    con.commit()
    print(f"\nDone. {n} activities written to {db_path}")


def do_update(client: StravaClient, db_path: str,
              verify_days: int = 30) -> None:
    """
    1. Fetch activities newer than the most-recent row in the DB.
    2. Re-fetch and re-verify the last `verify_days` days already stored.
    """
    con = open_db(db_path)

    # ---- Step 1: new activities ----
    row = con.execute(
        "SELECT MAX(start_date) as md FROM activities"
    ).fetchone()
    latest_date = row["md"] if row and row["md"] else None

    if latest_date:
        # Convert ISO string to Unix timestamp
        # Handle both with and without timezone suffix
        dt_str = latest_date.rstrip("Z")
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(dt_str, fmt.rstrip("z").rstrip("%z"))
                break
            except ValueError:
                continue
        else:
            dt = datetime.fromisoformat(dt_str)
        after_ts = int(dt.timestamp())
        print(f"Most recent activity in DB: {latest_date}")
        print(f"Fetching activities after {latest_date} …", flush=True)
    else:
        after_ts = None
        print("DB is empty – fetching everything …", flush=True)

    n_new = build_from_api(client, con, after=after_ts)
    print(f"  {n_new} new activities added.", flush=True)

    # ---- Step 2: verify recent window ----
    cutoff_dt = datetime.now(timezone.utc)
    cutoff_ts = int(cutoff_dt.timestamp())
    window_start_ts = cutoff_ts - verify_days * 86400

    print(f"\nRe-verifying the last {verify_days} days …", flush=True)
    # Fetch from API for the verification window
    api_acts: dict[int, dict] = {}
    for act in client.iter_all_activities(after=window_start_ts):
        api_acts[act["id"]] = act

    # Compare with what we have stored
    rows = con.execute(
        "SELECT id FROM activities WHERE start_date >= ?",
        (datetime.utcfromtimestamp(window_start_ts).isoformat(),)
    ).fetchall()
    db_ids = {r["id"] for r in rows}

    missing = set(api_acts.keys()) - db_ids
    extra   = db_ids - set(api_acts.keys())

    if missing:
        print(f"  Found {len(missing)} activities in API but not in DB "
              f"– inserting …", flush=True)
        for act_id in missing:
            upsert_activity(con, activity_to_row(api_acts[act_id], "api"))

    if extra:
        print(f"  WARNING: {len(extra)} activity IDs in DB not found via "
              f"API (possibly deleted or private): {extra}")

    # Overwrite all rows in the window with fresh API data
    for act in api_acts.values():
        upsert_activity(con, activity_to_row(act, "api"))

    con.commit()
    set_meta(con, "last_update", now_utc())
    con.commit()
    print(f"\nUpdate complete. DB: {db_path}")


# ---------------------------------------------------------------------------
# Backfill detail fields (workout_type, gear_name) — issue #2
# ---------------------------------------------------------------------------

WORKOUT_TYPE_LABELS = {
    0: "Default", 1: "Race", 2: "Long Run", 3: "Workout",
    10: "Default", 11: "Race", 12: "Workout",
}


def do_backfill_detail(client: StravaClient, db_path: str,
                       sport_types: Optional[list[str]] = None) -> None:
    """
    Fetch the full detail endpoint for activities where workout_type IS NULL,
    storing workout_type and refreshing gear_name.

    Respects the Read rate limit (100 req / 15 min, 1 000 req / day).
    Safe to interrupt and re-run — already-filled rows are skipped.
    """
    con = open_db(db_path)

    where_types = ""
    params: list = []
    if sport_types:
        placeholders = ",".join("?" * len(sport_types))
        where_types = f"AND sport_type IN ({placeholders})"
        params = sport_types

    rows = con.execute(
        f"SELECT id, sport_type FROM activities "
        f"WHERE workout_type IS NULL {where_types} "
        f"ORDER BY start_date_local DESC",
        params,
    ).fetchall()

    total = len(rows)
    print(f"Backfilling detail for {total} activities "
          f"(workout_type IS NULL{', sport_types=' + str(sport_types) if sport_types else ''}) …")
    print(f"At 1 000 req/day this will take ≥ {total / 1000:.1f} days.\n")

    for i, row in enumerate(rows, 1):
        act_id, sport_type = row["id"], row["sport_type"]
        try:
            detail = client._get(f"/activities/{act_id}")
        except Exception as exc:
            print(f"  [{i}/{total}] {act_id}: ERROR {exc}")
            continue

        wt        = detail.get("workout_type")
        gear_name = _s(detail, "gear", "name")

        con.execute(
            "UPDATE activities SET workout_type=?, gear_name=COALESCE(?, gear_name) "
            "WHERE id=?",
            (wt, gear_name, act_id),
        )
        if i % 50 == 0:
            con.commit()

        label = WORKOUT_TYPE_LABELS.get(wt, "—") if wt is not None else "—"
        print(f"  [{i}/{total}] {act_id}  {(sport_type or ''):<16} "
              f"workout_type={wt} ({label})  gear={gear_name or '—'}")

    con.commit()
    set_meta(con, "last_backfill_detail", now_utc())
    con.commit()
    print(f"\nBackfill complete. {total} activities processed.")


# ---------------------------------------------------------------------------
# Stats / reporting
# ---------------------------------------------------------------------------

M_TO_MILES = 0.000621371
M_TO_KM    = 0.001


def _fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s   = divmod(rem, 60)
    return f"{h}h {m:02d}m"


def do_stats(db_path: str) -> None:
    if not Path(db_path).exists():
        sys.exit(f"Database not found: {db_path}  (run build-api or build-archive first)")

    con = open_db(db_path)

    total = con.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    print(f"\n{'='*60}")
    print(f"  Strava Activity Database  —  {db_path}")
    print(f"{'='*60}")
    print(f"  Total activities: {total}")
    last_update = get_meta(con, "last_update") or get_meta(con, "last_full_pull") \
                  or get_meta(con, "last_archive_import")
    print(f"  Last sync:        {last_update or 'never'}")

    # Date range
    rng = con.execute(
        "SELECT MIN(start_date), MAX(start_date) FROM activities"
    ).fetchone()
    print(f"  Date range:       {rng[0][:10] if rng[0] else '?'} → "
          f"{rng[1][:10] if rng[1] else '?'}")

    print()
    print("── By sport type ─────────────────────────────────────────")
    rows = con.execute("""
        SELECT sport_type,
               COUNT(*) AS n,
               ROUND(SUM(distance_m) * ?, 1) AS miles,
               SUM(moving_time_s)              AS secs
        FROM activities
        GROUP BY sport_type
        ORDER BY n DESC
    """, (M_TO_MILES,)).fetchall()
    for r in rows:
        print(f"  {(r[0] or 'Unknown'):<18}  {r[1]:>5} activities  "
              f"{r[2] or 0:>8.1f} mi  "
              f"{_fmt_duration(r[3]):>10}")

    print()
    print("── Rides: miles per bike (gear) ──────────────────────────")
    rows = con.execute("""
        SELECT COALESCE(gear_name, gear_id, 'Unknown') AS bike,
               COUNT(*) AS n,
               ROUND(SUM(distance_m) * ?, 1)   AS miles,
               SUM(moving_time_s)                AS secs,
               SUM(commute)                      AS commutes
        FROM activities
        WHERE sport_type IN ('Ride','VirtualRide','EBikeRide','GravelRide',
                             'MountainBikeRide','Velomobile')
           OR type IN ('Ride','VirtualRide','EBikeRide')
        GROUP BY bike
        ORDER BY miles DESC
    """, (M_TO_MILES,)).fetchall()
    if rows:
        for r in rows:
            print(f"  {(r[0]):<28}  {r[1]:>4} rides  "
                  f"{r[2] or 0:>8.1f} mi  "
                  f"{_fmt_duration(r[3]):>9}  "
                  f"({r[4]} commutes)")
    else:
        print("  (no ride data)")

    print()
    print("── Weekly run mileage (last 12 weeks) ────────────────────")
    rows = con.execute("""
        SELECT strftime('%Y-W%W', start_date_local) AS week,
               COUNT(*) AS runs,
               ROUND(SUM(distance_m) * ?, 2) AS miles,
               SUM(moving_time_s) AS secs
        FROM activities
        WHERE sport_type IN ('Run','TrailRun','VirtualRun')
           OR type = 'Run'
        GROUP BY week
        ORDER BY week DESC
        LIMIT 12
    """, (M_TO_MILES,)).fetchall()
    if rows:
        for r in rows:
            print(f"  {r[0]}   {r[1]:>2} runs  "
                  f"{r[2] or 0:>6.1f} mi  {_fmt_duration(r[3])}")
    else:
        print("  (no run data)")

    print()
    print("── Weekly workout time (last 12 weeks, all types) ────────")
    rows = con.execute("""
        SELECT strftime('%Y-W%W', start_date_local) AS week,
               COUNT(*) AS acts,
               SUM(moving_time_s) AS secs
        FROM activities
        GROUP BY week
        ORDER BY week DESC
        LIMIT 12
    """).fetchall()
    if rows:
        for r in rows:
            print(f"  {r[0]}   {r[1]:>2} activities  "
                  f"{_fmt_duration(r[2])}")
    else:
        print("  (no data)")

    print()
    print("── Commute rides (all time) ──────────────────────────────")
    rows = con.execute("""
        SELECT strftime('%Y', start_date_local) AS yr,
               COUNT(*) AS n,
               ROUND(SUM(distance_m) * ?, 1) AS miles
        FROM activities
        WHERE commute = 1
          AND (sport_type LIKE '%Ride%' OR type LIKE '%Ride%')
        GROUP BY yr
        ORDER BY yr DESC
    """, (M_TO_MILES,)).fetchall()
    if rows:
        for r in rows:
            print(f"  {r[0]}   {r[1]:>3} commutes   {r[2] or 0:>7.1f} mi")
    else:
        print("  (no commute rides)")

    print(f"\n{'='*60}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def make_client(env_path: Path) -> StravaClient:
    client_id     = os.environ.get("STRAVA_CLIENT_ID", "")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET", "")
    access_token  = os.environ.get("STRAVA_ACCESS_TOKEN", "")
    refresh_token = os.environ.get("STRAVA_REFRESH_TOKEN", "")
    if not all([client_id, client_secret, refresh_token]):
        sys.exit(
            "Missing Strava credentials.  Copy .env.example → .env and fill in "
            "STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, and STRAVA_REFRESH_TOKEN."
        )
    return StravaClient(client_id, client_secret, access_token, refresh_token,
                        env_path=env_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build / update a local SQLite metadata DB of Strava activities.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("mode", choices=["build-archive", "build-api",
                                         "update", "stats",
                                         "backfill-detail"],
                        help="Operation to perform")
    parser.add_argument("archive", nargs="?",
                        help="(build-archive only) Path to Strava export ZIP")
    parser.add_argument("--db", default=None,
                        help="Override DB_PATH from .env")
    parser.add_argument("--verify-days", type=int, default=30,
                        help="(update) Days to re-verify (default: 30)")
    parser.add_argument("--sport-types", nargs="+", default=None,
                        metavar="TYPE",
                        help="(backfill-detail) Limit to these sport types, "
                             "e.g. --sport-types Run Ride")
    parser.add_argument("--env", default=".env",
                        help="Path to .env file (default: .env)")
    args = parser.parse_args()

    env_path = Path(args.env)
    load_dotenv(env_path, override=False)  # populate os.environ from .env

    db_path = args.db or os.environ.get("DB_PATH", "strava.db")

    # ---- dispatch ----
    if args.mode == "build-archive":
        if not args.archive:
            parser.error("build-archive requires the path to a Strava export ZIP")
        import_archive(args.archive, db_path)

    elif args.mode == "build-api":
        client = make_client(env_path)
        do_build_api(client, db_path)

    elif args.mode == "update":
        client = make_client(env_path)
        do_update(client, db_path, verify_days=args.verify_days)

    elif args.mode == "backfill-detail":
        client = make_client(env_path)
        do_backfill_detail(client, db_path, sport_types=args.sport_types)

    elif args.mode == "stats":
        do_stats(db_path)


if __name__ == "__main__":
    main()
