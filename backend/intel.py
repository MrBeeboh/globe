"""Live intel overlays: flights, satellites, active fires. Cached in memory."""
import logging
import time
from datetime import datetime, timezone

import httpx

log = logging.getLogger("intel")

UA = {"User-Agent": "globe-monitor/1.0 (personal research tool)"}
TIMEOUT = httpx.Timeout(25.0)

_cache: dict[str, dict] = {
    "flights": {"ts": 0, "data": [], "error": ""},
    "satellites": {"ts": 0, "data": [], "error": ""},
    "fires": {"ts": 0, "data": [], "error": ""},
    "vessels": {"ts": 0, "data": [], "error": "", "source": ""},
}

TTL = {
    "flights": 90,
    "satellites": 45,
    "fires": 600,
    "vessels": 120,
}


def _fresh(key: str) -> bool:
    return (time.time() - _cache[key]["ts"]) < TTL[key]


def _fetch_flights() -> list[dict]:
    with httpx.Client(timeout=TIMEOUT, headers=UA) as client:
        r = client.get("https://opensky-network.org/api/states/all")
        r.raise_for_status()
        states = r.json().get("states") or []
    out = []
    for s in states:
        if not s or len(s) < 11:
            continue
        lat, lon = s[6], s[5]
        if lat is None or lon is None:
            continue
        if s[8]:  # on ground
            continue
        alt = s[7] or 0
        if alt < 500:
            continue
        out.append({
            "id": s[0],
            "callsign": (s[1] or "").strip(),
            "country": s[2] or "",
            "lat": lat,
            "lon": lon,
            "alt_m": round(alt),
            "velocity_ms": round(s[9] or 0, 1),
            "heading": s[10],
        })
    out.sort(key=lambda x: -x["alt_m"])
    return out[:600]


def _fetch_satellites() -> list[dict]:
    sats = []
    with httpx.Client(timeout=TIMEOUT, headers=UA) as client:
        iss = client.get("https://api.wheretheiss.at/v1/satellites/25544").raise_for_status().json()
        sats.append({
            "id": "iss",
            "name": "International Space Station",
            "lat": iss["latitude"],
            "lon": iss["longitude"],
            "alt_km": round(iss.get("altitude", 0), 1),
            "velocity_kmh": round(iss.get("velocity", 0), 0),
            "visibility": iss.get("visibility", ""),
            "ts": iss.get("timestamp", 0),
        })
        try:
            tiangong = client.get("https://api.wheretheiss.at/v1/satellites/48274").raise_for_status().json()
            sats.append({
                "id": "tiangong",
                "name": "Tiangong Space Station",
                "lat": tiangong["latitude"],
                "lon": tiangong["longitude"],
                "alt_km": round(tiangong.get("altitude", 0), 1),
                "velocity_kmh": round(tiangong.get("velocity", 0), 0),
                "visibility": tiangong.get("visibility", ""),
                "ts": tiangong.get("timestamp", 0),
            })
        except Exception:
            pass
    return sats


def _fetch_fires() -> list[dict]:
    """NASA EONET open wildfires + NASA FIRMS VIIRS NRT (no API key, last 24h)."""
    out: list[dict] = []
    seen: set[str] = set()

    with httpx.Client(timeout=TIMEOUT, headers=UA, follow_redirects=True) as client:
        # EONET open wildfire events
        try:
            data = client.get(
                "https://eonet.gsfc.nasa.gov/api/v3/events",
                params={"category": "wildfires", "status": "open", "limit": 80},
            ).raise_for_status().json()
            for ev in data.get("events", []):
                for geom in ev.get("geometry", []):
                    coords = geom.get("coordinates")
                    if not coords or len(coords) < 2:
                        continue
                    lon, lat = coords[0], coords[1]
                    key = f"{lat:.2f},{lon:.2f}"
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({
                        "id": f"eonet-{ev['id']}",
                        "lat": lat,
                        "lon": lon,
                        "title": ev.get("title", "Wildfire"),
                        "source": "eonet",
                        "brightness": None,
                        "ts": geom.get("date") or ev.get("updated") or "",
                    })
        except Exception as e:
            log.warning("eonet fires: %s", e)

        # FIRMS VIIRS SNPP NRT global (last 24h CSV, public download)
        try:
            csv = client.get(
                "https://firms.modaps.eosdis.nasa.gov/api/area/csv/VIIRS_SNPP_NRT/world/1",
                params={"date": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
            )
            if csv.status_code == 401 or "MAP_KEY" in csv.text[:200]:
                # fallback: older public CSV endpoint
                csv = client.get(
                    "https://firms.modaps.eosdis.nasa.gov/data/active_fire/csv/VIIRS_SNPP_NRT_global.csv"
                )
            if csv.status_code == 200 and "," in csv.text:
                lines = csv.text.strip().splitlines()[1:401]
                for line in lines:
                    parts = line.split(",")
                    if len(parts) < 3:
                        continue
                    try:
                        lat, lon = float(parts[0]), float(parts[1])
                        bright = float(parts[2]) if parts[2] else 0
                    except ValueError:
                        continue
                    key = f"{lat:.2f},{lon:.2f}"
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({
                        "id": f"firms-{key}",
                        "lat": lat,
                        "lon": lon,
                        "title": "Active fire (VIIRS)",
                        "source": "firms",
                        "brightness": bright,
                        "ts": parts[5] if len(parts) > 5 else "",
                    })
        except Exception as e:
            log.warning("firms fires: %s", e)

    return out[:500]


def get_intel(kind: str) -> dict:
    if kind not in _cache:
        return {"error": "unknown"}
    if kind == "vessels":
        from . import maritime
        return maritime.get_vessels()
    if not _fresh(kind):
        try:
            if kind == "flights":
                data = _fetch_flights()
            elif kind == "satellites":
                data = _fetch_satellites()
            else:
                data = _fetch_fires()
            _cache[kind] = {"ts": time.time(), "data": data, "error": ""}
        except Exception as e:
            log.warning("%s fetch failed: %s", kind, e)
            _cache[kind]["error"] = str(e)
            if not _cache[kind]["data"]:
                _cache[kind]["ts"] = time.time() - TTL[kind] + 30
    entry = _cache[kind]
    return {
        "kind": kind,
        "count": len(entry["data"]),
        "cached_sec_ago": round(time.time() - entry["ts"]) if entry["ts"] else None,
        "error": entry["error"],
        "items": entry["data"],
    }


def refresh_all():
    for kind in ("flights", "satellites", "fires", "vessels"):
        if kind == "vessels":
            from . import maritime
            maritime.refresh()
        else:
            _cache[kind]["ts"] = 0
            get_intel(kind)