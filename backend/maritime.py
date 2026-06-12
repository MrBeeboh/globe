"""Maritime AIS — Digitraffic (Baltic) + conflict-region vessel filter."""
import logging
import time

import httpx

log = logging.getLogger("maritime")

UA = {
    "User-Agent": "Globe/2.0 (open geospatial intelligence)",
    "Digitraffic-User": "Globe/2.0",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
}
TIMEOUT = httpx.Timeout(25.0)

# Conflict-relevant maritime zones (lat/lon boxes)
CONFLICT_BOXES = [
    {"name": "black_sea", "lat_min": 40.5, "lat_max": 47.5, "lon_min": 27.0, "lon_max": 42.0},
    {"name": "med_east", "lat_min": 30.0, "lat_max": 37.0, "lon_min": 32.0, "lon_max": 36.5},
    {"name": "red_sea", "lat_min": 12.0, "lat_max": 30.0, "lon_min": 32.0, "lon_max": 44.5},
    {"name": "persian_gulf", "lat_min": 23.0, "lat_max": 30.5, "lon_min": 48.0, "lon_max": 57.5},
    {"name": "baltic", "lat_min": 53.0, "lat_max": 66.0, "lon_min": 9.0, "lon_max": 30.5},
    {"name": "eastern_med", "lat_min": 31.0, "lat_max": 37.5, "lon_min": 25.0, "lon_max": 36.5},
]

_cache: dict = {"ts": 0, "data": [], "error": "", "source": ""}
TTL = 120


def _in_conflict_zone(lat: float, lon: float) -> bool:
    for box in CONFLICT_BOXES:
        if box["lat_min"] <= lat <= box["lat_max"] and box["lon_min"] <= lon <= box["lon_max"]:
            return True
    return False


def _parse_digitraffic(data: dict) -> list[dict]:
    out: list[dict] = []
    for feat in data.get("features") or []:
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        if lat is None or lon is None:
            continue
        mmsi = props.get("mmsi") or props.get("shipType")
        name = (props.get("name") or "").strip() or f"MMSI {mmsi or '?'}"
        sog = props.get("sog")
        cog = props.get("cog")
        ship_type = props.get("shipType")
        out.append({
            "id": str(mmsi or f"{lat:.4f},{lon:.4f}"),
            "name": name,
            "mmsi": mmsi,
            "lat": lat,
            "lon": lon,
            "sog_kn": round(sog, 1) if sog is not None else None,
            "cog_deg": round(cog, 1) if cog is not None else None,
            "ship_type": ship_type,
            "source": "digitraffic",
            "zone": "baltic" if _in_conflict_zone(lat, lon) else "other",
        })
    return out


def fetch_vessels() -> list[dict]:
    with httpx.Client(timeout=TIMEOUT, headers=UA, follow_redirects=True) as client:
        r = client.get("https://meri.digitraffic.fi/api/ais/v1/locations")
        r.raise_for_status()
        data = r.json()
    vessels = _parse_digitraffic(data)
    # Prefer conflict-zone vessels; always include Baltic (Ukraine grain corridor relevance)
    conflict = [v for v in vessels if _in_conflict_zone(v["lat"], v["lon"])]
    if conflict:
        return conflict[:800]
    return vessels[:800]


def get_vessels() -> dict:
    if _cache["ts"] and (time.time() - _cache["ts"]) < TTL:
        return {
            "kind": "vessels",
            "count": len(_cache["data"]),
            "cached_sec_ago": round(time.time() - _cache["ts"]),
            "error": _cache["error"],
            "source": _cache["source"],
            "items": _cache["data"],
        }
    try:
        data = fetch_vessels()
        _cache.update({
            "ts": time.time(),
            "data": data,
            "error": "",
            "source": "digitraffic",
        })
    except Exception as e:
        log.warning("vessels fetch failed: %s", e)
        _cache["error"] = str(e)
        if not _cache["data"]:
            _cache["ts"] = time.time() - TTL + 30
    return {
        "kind": "vessels",
        "count": len(_cache["data"]),
        "cached_sec_ago": round(time.time() - _cache["ts"]) if _cache["ts"] else None,
        "error": _cache["error"],
        "source": _cache.get("source", ""),
        "items": _cache["data"],
    }


def refresh():
    _cache["ts"] = 0
    get_vessels()