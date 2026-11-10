"""
streams.py  –  Per-activity time-series ("streams") for the activity viewer.

Full-resolution streams live in a local SQLite file, ``streams.db``
(gitignored: it is hundreds of MB and fully re-derivable from the Strava API
or a bulk-export archive). ``build_html.py`` downsamples them into small
``streams/<id>.json`` files that ``viewer.html`` charts.

Canonical stream format: a dict keyed by Strava stream type, each value a
list aligned with ``time`` (seconds since start). Keys used:

    time, latlng ([lat, lng] or None), distance (m), altitude (m),
    heartrate (bpm), watts, cadence (rpm; per-leg for runs, as Strava and
    FIT both record it), velocity_smooth (m/s), temp (°C), moving (bool)

Sources:
  api      GET /activities/{id}/streams  (1 read request per activity)
  archive  original .fit / .gpx / .tcx (optionally .gz) from a Strava export
  none     the API returned 404 (manual activity, no data); not retried
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import math
import sqlite3
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional
from xml.etree import ElementTree as ET

STREAM_KEYS = ("time", "latlng", "distance", "altitude", "heartrate", "watts",
               "cadence", "velocity_smooth", "temp", "moving")

SCHEMA = """
CREATE TABLE IF NOT EXISTS streams (
    activity_id INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,      -- api | archive | none
    n_points    INTEGER NOT NULL,
    keys        TEXT NOT NULL,      -- comma-separated stream keys present
    data        BLOB,               -- zlib(JSON canonical dict); NULL for none
    fetched_at  TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def open_streams_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def save(con: sqlite3.Connection, activity_id: int, source: str,
         streams: Optional[dict]) -> None:
    if streams is None:
        con.execute("INSERT OR REPLACE INTO streams VALUES (?,?,?,?,?,?)",
                    (activity_id, "none", 0, "", None, _now()))
        return
    keys = [k for k in STREAM_KEYS if k in streams]
    blob = zlib.compress(json.dumps({k: streams[k] for k in keys},
                                    separators=(",", ":")).encode(), 9)
    con.execute("INSERT OR REPLACE INTO streams VALUES (?,?,?,?,?,?)",
                (activity_id, source, len(streams["time"]), ",".join(keys),
                 blob, _now()))


def load(con: sqlite3.Connection, activity_id: int) -> Optional[dict]:
    row = con.execute("SELECT data FROM streams WHERE activity_id=?",
                      (activity_id,)).fetchone()
    if not row or row[0] is None:
        return None
    return json.loads(zlib.decompress(row[0]))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def fetch_api(client, activity_id: int) -> Optional[dict]:
    """Return canonical streams, or None if Strava has none (404)."""
    import requests
    try:
        raw = client._get(f"/activities/{activity_id}/streams", {
            "keys": ",".join(STREAM_KEYS), "key_by_type": "true"})
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return None
        raise
    if "time" not in raw:
        return None
    return {k: raw[k]["data"] for k in STREAM_KEYS if k in raw}


def fetch_missing(client, meta_con: sqlite3.Connection,
                  streams_con: sqlite3.Connection, budget: int) -> int:
    """Fetch streams for up to `budget` activities that have none stored,
    newest first. Manual activities are skipped (they never have streams).
    Returns the number of API requests made."""
    have = {r[0] for r in streams_con.execute("SELECT activity_id FROM streams")}
    todo = [r[0] for r in meta_con.execute(
        "SELECT id FROM activities WHERE COALESCE(manual,0)=0 "
        "ORDER BY start_date DESC") if r[0] not in have]
    print(f"\nStreams: {len(todo)} activities missing; fetching up to {budget} …",
          flush=True)
    n = 0
    for aid in todo[:budget]:
        s = fetch_api(client, aid)
        save(streams_con, aid, "api", s)
        n += 1
        if n % 25 == 0:
            streams_con.commit()
            print(f"  {n}/{min(budget, len(todo))}", flush=True)
    streams_con.commit()
    print(f"  fetched {n}; {len(todo) - n} still missing.", flush=True)
    return n


# ---------------------------------------------------------------------------
# Archive (.fit / .gpx / .tcx, optionally gzipped)
# ---------------------------------------------------------------------------

def _haversine(a, b) -> float:
    R = 6371008.8
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def _from_points(pts: list[dict]) -> Optional[dict]:
    """pts: dicts with 'ts' (datetime) and any of lat, lng, alt, dist, hr,
    cad, watts, speed, temp. Returns canonical streams or None."""
    pts = [p for p in pts if p.get("ts") is not None]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda p: p["ts"])
    t0 = pts[0]["ts"]
    out: dict = {"time": [int(round((p["ts"] - t0).total_seconds())) for p in pts]}

    ll = [[p["lat"], p["lng"]] if p.get("lat") is not None and p.get("lng") is not None
          else None for p in pts]
    if any(ll):
        out["latlng"] = ll

    if any(p.get("dist") is not None for p in pts):
        last = 0.0
        d = []
        for p in pts:
            if p.get("dist") is not None:
                last = p["dist"]
            d.append(last)
        out["distance"] = d
    elif "latlng" in out:
        d, total, prev = [], 0.0, None
        for x in ll:
            if x is not None:
                if prev is not None:
                    total += _haversine(prev, x)
                prev = x
            d.append(round(total, 1))
        out["distance"] = d

    for src, key in (("alt", "altitude"), ("hr", "heartrate"), ("watts", "watts"),
                     ("cad", "cadence"), ("speed", "velocity_smooth"),
                     ("temp", "temp")):
        vals = [p.get(src) for p in pts]
        if any(v is not None for v in vals):
            out[key] = vals
    return out


def _parse_fit(data: bytes) -> Optional[dict]:
    from garmin_fit_sdk import Decoder, Stream
    msgs, _errors = Decoder(Stream.from_byte_array(bytearray(data))).read()
    k = 180 / 2 ** 31
    pts = []
    for r in msgs.get("record_mesgs", []):
        lat, lng = r.get("position_lat"), r.get("position_long")
        pts.append({
            "ts": r.get("timestamp"),
            "lat": lat * k if lat is not None else None,
            "lng": lng * k if lng is not None else None,
            "alt": r.get("enhanced_altitude", r.get("altitude")),
            "dist": r.get("distance"),
            "hr": r.get("heart_rate"),
            "cad": r.get("cadence"),
            "watts": r.get("power"),
            "speed": r.get("enhanced_speed", r.get("speed")),
            "temp": r.get("temperature"),
        })
    return _from_points(pts)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))


def _num(s: Optional[str]) -> Optional[float]:
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def _parse_gpx(data: bytes) -> Optional[dict]:
    root = ET.fromstring(data.lstrip())
    pts = []
    for el in root.iter():
        if _local(el.tag) != "trkpt":
            continue
        p = {"lat": _num(el.get("lat")), "lng": _num(el.get("lon"))}
        for c in el.iter():
            n = _local(c.tag)
            if n == "ele":
                p["alt"] = _num(c.text)
            elif n == "time":
                p["ts"] = _ts(c.text)
            elif n in ("hr", "heartrate"):
                p["hr"] = _num(c.text)
            elif n in ("cad", "cadence"):
                p["cad"] = _num(c.text)
            elif n in ("power", "watts"):
                p["watts"] = _num(c.text)
            elif n in ("atemp", "temp"):
                p["temp"] = _num(c.text)
        pts.append(p)
    return _from_points(pts)


def _parse_tcx(data: bytes) -> Optional[dict]:
    # Strava's TCX exports often start with whitespace before <?xml.
    root = ET.fromstring(data.lstrip())
    pts = []
    for tp in root.iter():
        if _local(tp.tag) != "Trackpoint":
            continue
        p: dict = {}
        for c in tp.iter():
            n = _local(c.tag)
            if n == "Time":
                p["ts"] = _ts(c.text)
            elif n == "LatitudeDegrees":
                p["lat"] = _num(c.text)
            elif n == "LongitudeDegrees":
                p["lng"] = _num(c.text)
            elif n == "AltitudeMeters":
                p["alt"] = _num(c.text)
            elif n == "DistanceMeters":
                p["dist"] = _num(c.text)
            elif n == "HeartRateBpm":
                p["hr"] = _num(next((v.text for v in c if _local(v.tag) == "Value"), None))
            elif n in ("Cadence", "RunCadence"):
                p["cad"] = _num(c.text)
            elif n == "Watts":
                p["watts"] = _num(c.text)
            elif n == "Speed":
                p["speed"] = _num(c.text)
        pts.append(p)
    return _from_points(pts)


def parse_activity_file(name: str, data: bytes) -> Optional[dict]:
    if name.endswith(".gz"):
        data = gzip.decompress(data)
        name = name[:-3]
    ext = name.rsplit(".", 1)[-1].lower()
    if ext == "fit":
        return _parse_fit(data)
    if ext == "gpx":
        return _parse_gpx(data)
    if ext == "tcx":
        return _parse_tcx(data)
    raise ValueError(f"unsupported activity file type: {name}")


def _archive_entries(path: str) -> Iterator[tuple[int, str, bytes]]:
    """Yield (activity_id, filename, bytes) from an export ZIP or its
    extracted directory, using activities.csv for the id -> file mapping."""
    p = Path(path)
    if p.is_dir():
        read = lambda n: (p / n).read_bytes()  # noqa: E731
        csv_text = (p / "activities.csv").read_text(encoding="utf-8-sig")
        zf = None
    else:
        zf = zipfile.ZipFile(p)
        read = zf.read
        csv_text = zf.read("activities.csv").decode("utf-8-sig")
    try:
        for r in csv.DictReader(io.StringIO(csv_text)):
            fn = (r.get("Filename") or "").strip()
            if fn:
                yield int(r["Activity ID"]), fn, read(fn)
    finally:
        if zf:
            zf.close()


def import_archive(path: str, meta_con: sqlite3.Connection,
                   streams_con: sqlite3.Connection, force: bool = False) -> None:
    known = {r[0] for r in meta_con.execute("SELECT id FROM activities")}
    have = {r[0] for r in streams_con.execute(
        "SELECT activity_id FROM streams WHERE source != 'none'")}
    n_ok = n_skip = n_empty = n_err = n_unknown = 0
    for aid, fn, data in _archive_entries(path):
        if aid not in known:
            n_unknown += 1
            continue
        if aid in have and not force:
            n_skip += 1
            continue
        try:
            s = parse_activity_file(fn, data)
        except Exception as exc:  # one bad file must not stop a 9k-file import
            print(f"  {aid} {fn}: ERROR {exc}")
            n_err += 1
            continue
        if s is None:
            n_empty += 1
            continue
        save(streams_con, aid, "archive", s)
        n_ok += 1
        if n_ok % 200 == 0:
            streams_con.commit()
            print(f"  imported {n_ok} …", flush=True)
    streams_con.commit()
    print(f"Archive streams: {n_ok} imported, {n_skip} already had streams, "
          f"{n_empty} files without track points, {n_err} errors, "
          f"{n_unknown} not in strava.db.")


# ---------------------------------------------------------------------------
# Downsampling for publication
# ---------------------------------------------------------------------------

def encode_polyline(points: list) -> str:
    out, plat, plng = [], 0, 0
    for lat, lng in points:
        ilat, ilng = round(lat * 1e5), round(lng * 1e5)
        for d in (ilat - plat, ilng - plng):
            v = ~(d << 1) if d < 0 else d << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plng = ilat, ilng
    return "".join(out)


def _mean(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def downsample(s: dict, max_points: int = 600) -> dict:
    """Bucket-average to <= max_points samples and round for compact JSON.

    Output: {"n", "t": [s], "d": [m], "alt": [m*10 ints → /10], "hr", "w",
    "cad", "v": [cm/s], "temp", "ll": encoded polyline (points without GPS are
    dropped from the line; "lli" maps each sample to its polyline index or -1)}.
    """
    n = len(s["time"])
    step = max(1, math.ceil(n / max_points))
    buckets = [range(i, min(i + step, n)) for i in range(0, n, step)]

    def col(key, fn, scale=1.0, nd=0):
        if key not in s:
            return None
        src = s[key]
        vals = [fn([src[i] for i in b]) for b in buckets]
        if all(v is None for v in vals):
            return None
        return [None if v is None else (round(v * scale) if nd == 0 else round(v * scale, nd))
                for v in vals]

    last = lambda xs: next((x for x in reversed(xs) if x is not None), None)  # noqa: E731
    out: dict = {"n": len(buckets), "t": col("time", last)}
    for key, name, fn, scale in (("distance", "d", last, 1),
                                 ("altitude", "alt", _mean, 10),
                                 ("heartrate", "hr", _mean, 1),
                                 ("watts", "w", _mean, 1),
                                 ("cadence", "cad", _mean, 1),
                                 ("velocity_smooth", "v", _mean, 100),
                                 ("temp", "temp", _mean, 1)):
        c = col(key, fn, scale)
        if c is not None:
            out[name] = c
    if "latlng" in s:
        line, idx = [], []
        for b in buckets:
            p = next((s["latlng"][i] for i in b if s["latlng"][i]), None)
            if p:
                idx.append(len(line))
                line.append(p)
            else:
                idx.append(-1)
        if len(line) > 1:
            out["ll"] = encode_polyline(line)
            out["lli"] = idx if -1 in idx else None
            if out["lli"] is None:
                del out["lli"]
    return out
