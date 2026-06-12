"""Lightweight gazetteer for geolocating news text.

Country centroids are derived at import time from the bundled Natural Earth
TopoJSON (data/countries-110m.json), so every recognized country gets
coordinates without an external geocoder. A curated city list covers places
that dominate world news but aren't country names.
"""
import json
import os
import re

_ATLAS = os.path.join(os.path.dirname(__file__), "..", "data", "countries-110m.json")

# (name, lat, lon, country) — newsworthy cities and regions
CITIES = [
    ("Kyiv", 50.45, 30.52, "Ukraine"), ("Kharkiv", 49.99, 36.23, "Ukraine"),
    ("Odesa", 46.48, 30.73, "Ukraine"), ("Donetsk", 48.02, 37.80, "Ukraine"),
    ("Crimea", 45.30, 34.40, "Ukraine"), ("Zaporizhzhia", 47.84, 35.14, "Ukraine"),
    ("Moscow", 55.76, 37.62, "Russia"), ("St Petersburg", 59.93, 30.34, "Russia"),
    ("Gaza", 31.50, 34.47, "Palestine"), ("Rafah", 31.29, 34.25, "Palestine"),
    ("West Bank", 31.95, 35.30, "Palestine"), ("Jerusalem", 31.77, 35.21, "Israel"),
    ("Tel Aviv", 32.09, 34.78, "Israel"), ("Beirut", 33.89, 35.50, "Lebanon"),
    ("Damascus", 33.51, 36.29, "Syria"), ("Aleppo", 36.20, 37.16, "Syria"),
    ("Baghdad", 33.31, 44.37, "Iraq"), ("Mosul", 36.34, 43.13, "Iraq"),
    ("Tehran", 35.69, 51.39, "Iran"), ("Kabul", 34.55, 69.21, "Afghanistan"),
    ("Islamabad", 33.69, 73.06, "Pakistan"), ("Karachi", 24.86, 67.01, "Pakistan"),
    ("New Delhi", 28.61, 77.21, "India"), ("Mumbai", 19.08, 72.88, "India"),
    ("Kashmir", 34.08, 74.80, "India"), ("Beijing", 39.90, 116.40, "China"),
    ("Shanghai", 31.23, 121.47, "China"), ("Hong Kong", 22.32, 114.17, "China"),
    ("Taipei", 25.03, 121.57, "Taiwan"), ("Pyongyang", 39.02, 125.74, "North Korea"),
    ("Seoul", 37.57, 126.98, "South Korea"), ("Tokyo", 35.68, 139.69, "Japan"),
    ("Khartoum", 15.50, 32.56, "Sudan"), ("Darfur", 13.50, 25.00, "Sudan"),
    ("Mogadishu", 2.05, 45.32, "Somalia"), ("Addis Ababa", 9.03, 38.74, "Ethiopia"),
    ("Tigray", 14.04, 38.32, "Ethiopia"), ("Nairobi", -1.29, 36.82, "Kenya"),
    ("Kinshasa", -4.32, 15.31, "DR Congo"), ("Goma", -1.66, 29.22, "DR Congo"),
    ("Lagos", 6.52, 3.38, "Nigeria"), ("Abuja", 9.06, 7.40, "Nigeria"),
    ("Tripoli", 32.89, 13.19, "Libya"), ("Cairo", 30.04, 31.24, "Egypt"),
    ("Sanaa", 15.37, 44.19, "Yemen"), ("Aden", 12.79, 45.04, "Yemen"),
    ("Riyadh", 24.71, 46.68, "Saudi Arabia"), ("Dubai", 25.20, 55.27, "UAE"),
    ("Istanbul", 41.01, 28.98, "Turkey"), ("Ankara", 39.93, 32.86, "Turkey"),
    ("London", 51.51, -0.13, "United Kingdom"), ("Paris", 48.86, 2.35, "France"),
    ("Berlin", 52.52, 13.41, "Germany"), ("Brussels", 50.85, 4.35, "Belgium"),
    ("Warsaw", 52.23, 21.01, "Poland"), ("Belgrade", 44.79, 20.45, "Serbia"),
    ("Washington", 38.91, -77.04, "United States"), ("New York", 40.71, -74.01, "United States"),
    ("Los Angeles", 34.05, -118.24, "United States"), ("Mexico City", 19.43, -99.13, "Mexico"),
    ("Bogota", 4.71, -74.07, "Colombia"), ("Caracas", 10.49, -66.88, "Venezuela"),
    ("Port-au-Prince", 18.54, -72.34, "Haiti"), ("Brasilia", -15.79, -47.88, "Brazil"),
    ("Buenos Aires", -34.60, -58.38, "Argentina"), ("Yangon", 16.87, 96.20, "Myanmar"),
    ("Naypyidaw", 19.76, 96.08, "Myanmar"), ("Bangkok", 13.76, 100.50, "Thailand"),
    ("Manila", 14.60, 120.98, "Philippines"), ("Jakarta", -6.21, 106.85, "Indonesia"),
    ("Canberra", -35.28, 149.13, "Australia"), ("Sahel", 14.50, 0.0, "Mali"),
    ("Bamako", 12.64, -8.00, "Mali"), ("Ouagadougou", 12.37, -1.52, "Burkina Faso"),
    ("Niamey", 13.51, 2.13, "Niger"), ("N'Djamena", 12.13, 15.06, "Chad"),
    ("Juba", 4.86, 31.57, "South Sudan"), ("Bangui", 4.39, 18.56, "Central African Republic"),
    ("Tbilisi", 41.72, 44.79, "Georgia"), ("Yerevan", 40.18, 44.51, "Armenia"),
    ("Baku", 40.41, 49.87, "Azerbaijan"), ("Minsk", 53.90, 27.57, "Belarus"),
    ("Chisinau", 47.01, 28.86, "Moldova"), ("Sarajevo", 43.86, 18.41, "Bosnia and Herzegovina"),
    ("Pristina", 42.66, 21.17, "Kosovo"), ("Havana", 23.11, -82.37, "Cuba"),
]

# Common name → atlas name fixups so headline text matches Natural Earth names
COUNTRY_ALIASES = {
    "USA": "United States of America", "U.S.": "United States of America",
    "United States": "United States of America", "America": "United States of America",
    "UK": "United Kingdom", "Britain": "United Kingdom",
    "DRC": "Dem. Rep. Congo", "DR Congo": "Dem. Rep. Congo",
    "Democratic Republic of Congo": "Dem. Rep. Congo",
    "Republic of Congo": "Congo", "Ivory Coast": "Côte d'Ivoire",
    "South Korea": "South Korea", "North Korea": "North Korea",
    "Czech Republic": "Czechia", "Burma": "Myanmar",
    "Palestinian": "Palestine", "Gaza Strip": "Palestine",
    "UAE": "United Arab Emirates", "Emirates": "United Arab Emirates",
    "Bosnia": "Bosnia and Herzegovina", "Macedonia": "North Macedonia",
    "Central African Republic": "Central African Rep.",
    "South Sudan": "S. Sudan", "Equatorial Guinea": "Eq. Guinea",
    "Dominican Republic": "Dominican Rep.", "Solomon Islands": "Solomon Is.",
}


def _polygon_centroid(ring):
    """Planar centroid of a lon/lat ring — good enough for label points."""
    area = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        f = x0 * y1 - x1 * y0
        area += f
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    if abs(area) < 1e-9:
        return ring[0]
    area *= 0.5
    return (cx / (6 * area), cy / (6 * area))


def _decode_topojson_centroids() -> dict:
    """Return {country_name: (lat, lon)} using each country's largest polygon."""
    with open(_ATLAS) as f:
        topo = json.load(f)
    tf = topo.get("transform", {})
    sx, sy = tf.get("scale", [1, 1])
    tx, ty = tf.get("translate", [0, 0])
    arcs = []
    for arc in topo["arcs"]:
        pts, x, y = [], 0, 0
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring_coords(arc_idxs):
        pts = []
        for idx in arc_idxs:
            a = arcs[idx] if idx >= 0 else list(reversed(arcs[~idx]))
            pts.extend(a if not pts else a[1:])
        return pts

    out = {}
    for geom in topo["objects"]["countries"]["geometries"]:
        name = (geom.get("properties") or {}).get("name")
        if not name:
            continue
        polys = []
        if geom["type"] == "Polygon":
            polys = [geom["arcs"]]
        elif geom["type"] == "MultiPolygon":
            polys = geom["arcs"]
        best, best_len = None, -1
        for poly in polys:
            ring = ring_coords(poly[0])
            if len(ring) > best_len:
                best, best_len = ring, len(ring)
        if best:
            lon, lat = _polygon_centroid(best)
            out[name] = (round(lat, 2), round(lon, 2))
    return out


COUNTRY_CENTROIDS = _decode_topojson_centroids()

# Build matcher: longest names first so "South Sudan" wins over "Sudan"
_TERMS = []
for name, (lat, lon) in COUNTRY_CENTROIDS.items():
    _TERMS.append((name, lat, lon, name))
for alias, target in COUNTRY_ALIASES.items():
    if target in COUNTRY_CENTROIDS:
        lat, lon = COUNTRY_CENTROIDS[target]
        _TERMS.append((alias, lat, lon, target))
for city, lat, lon, country in CITIES:
    _TERMS.append((city, lat, lon, country))
_TERMS.sort(key=lambda t: -len(t[0]))
_PATTERNS = [(re.compile(r"\b" + re.escape(t[0]) + r"\b", re.IGNORECASE), t) for t in _TERMS]


def locate(text: str):
    """Find the first (longest-name) place mention. Returns (lat, lon, place, country) or None."""
    for pat, (name, lat, lon, country) in _PATTERNS:
        if pat.search(text):
            place = name if name == country else f"{name}, {country}"
            return (lat, lon, place, country)
    return None
