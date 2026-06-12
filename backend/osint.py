"""OSINT helpers — reverse geocode & coordinate validation."""
import logging

import httpx

log = logging.getLogger("osint")

UA = {"User-Agent": "Globe/2.0 (open geospatial intelligence)"}
TIMEOUT = httpx.Timeout(12.0)


def reverse_geocode(lat: float, lon: float) -> dict:
    try:
        with httpx.Client(timeout=TIMEOUT, headers=UA) as client:
            r = client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lon, "format": "json", "zoom": 10},
            )
            r.raise_for_status()
            data = r.json()
        addr = data.get("address") or {}
        return {
            "lat": lat,
            "lon": lon,
            "display_name": data.get("display_name", ""),
            "country": addr.get("country", ""),
            "city": addr.get("city") or addr.get("town") or addr.get("village") or "",
            "source": "nominatim",
        }
    except Exception as e:
        log.warning("reverse geocode failed: %s", e)
        return {"lat": lat, "lon": lon, "display_name": "", "error": str(e)}