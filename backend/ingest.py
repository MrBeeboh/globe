"""Event ingestion: GDELT 2.0, USGS earthquakes, GDACS disasters, news RSS."""
import csv
import hashlib
import io
import logging
import re
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import httpx

from . import db, geo

log = logging.getLogger("ingest")

UA = {"User-Agent": "globe-monitor/1.0 (personal research tool)"}
TIMEOUT = httpx.Timeout(30.0)


def _id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.removeprefix("www.")
    except Exception:
        return ""


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# ---------------------------------------------------------------- GDELT 2.0

GDELT_LASTUPDATE = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"

# CAMEO root code → (category, human description)
CAMEO_ROOT = {
    "10": ("diplomacy", "Demand issued"),
    "11": ("diplomacy", "Disapproval / accusation"),
    "12": ("diplomacy", "Rejection / refusal"),
    "13": ("military", "Threat issued"),
    "14": ("unrest", "Protest / demonstration"),
    "15": ("military", "Force posture / mobilization"),
    "16": ("diplomacy", "Relations reduced / sanctions"),
    "17": ("conflict", "Coercion / repression"),
    "18": ("conflict", "Assault / attack"),
    "19": ("conflict", "Armed clash / fighting"),
    "20": ("conflict", "Mass violence"),
}

# Diplomacy-class events are noisy; require broader coverage before keeping
MIN_ARTICLES = {"diplomacy": 10, "military": 4, "unrest": 3, "conflict": 2}


def ingest_gdelt() -> int:
    try:
        with httpx.Client(timeout=TIMEOUT, headers=UA, follow_redirects=True) as client:
            txt = client.get(GDELT_LASTUPDATE).raise_for_status().text
            export_url = next(
                (line.split()[-1] for line in txt.splitlines() if "export.CSV" in line), None
            )
            if not export_url:
                raise RuntimeError("no export url in lastupdate.txt")
            blob = client.get(export_url).raise_for_status().content
        zf = zipfile.ZipFile(io.BytesIO(blob))
        raw = zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
        rows = _parse_gdelt(raw)
        n = db.insert_events(rows)
        db.log_ingest("gdelt", n)
        log.info("gdelt: %d parsed, %d inserted", len(rows), n)
        return n
    except Exception as e:
        log.warning("gdelt failed: %s", e)
        db.log_ingest("gdelt", 0, str(e))
        return 0


def _parse_gdelt(raw: str) -> list[dict]:
    out, seen_urls = [], set()
    for rec in csv.reader(io.StringIO(raw), delimiter="\t"):
        if len(rec) < 61:
            continue
        root = rec[28]
        meta = CAMEO_ROOT.get(root)
        if not meta:
            continue
        category, desc = meta
        try:
            lat, lon = float(rec[56]), float(rec[57])
            goldstein = float(rec[30] or 0)
            articles = int(rec[33] or 0)
        except ValueError:
            continue
        if articles < MIN_ARTICLES[category]:
            continue
        url = rec[60]
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        a1, a2 = rec[6].title(), rec[16].title()
        actors = " / ".join(p for p in (a1, a2) if p)
        place = rec[52]
        country = place.split(",")[-1].strip() if place else ""
        title = desc
        if actors:
            title += f": {actors}"
        if place:
            title += f" — {place.split(',')[0].strip()}"
        # severity: hostility (negative Goldstein) weighted with media coverage
        sev = _clamp((-goldstein / 10) * 0.65 + _clamp(articles / 60) * 0.35)
        if category == "conflict":
            sev = max(sev, 0.45)
        ts = rec[59]  # DATEADDED YYYYMMDDHHMMSS
        try:
            ts_iso = datetime.strptime(ts, "%Y%m%d%H%M%S").replace(
                tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append({
            "id": _id("gdelt", rec[0]),
            "ts": ts_iso,
            "title": title,
            "summary": f"GDELT-coded event (CAMEO {rec[26]}). "
                       f"Goldstein {goldstein:+.1f}, {articles} articles, tone {rec[34][:6]}.",
            "url": url,
            "source": _domain(url),
            "channel": "gdelt",
            "category": category,
            "severity": round(sev, 2),
            "lat": lat, "lon": lon,
            "place": place, "country": country,
            "actors": actors,
        })
    return out


# ---------------------------------------------------------------- USGS earthquakes

USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"


def ingest_usgs() -> int:
    try:
        with httpx.Client(timeout=TIMEOUT, headers=UA) as client:
            data = client.get(USGS_FEED).raise_for_status().json()
        rows = []
        for f in data.get("features", []):
            p, g = f["properties"], f["geometry"]["coordinates"]
            mag = p.get("mag") or 0
            ts = datetime.fromtimestamp(p["time"] / 1000, tz=timezone.utc)
            rows.append({
                "id": _id("usgs", f["id"]),
                "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "title": f"M{mag:.1f} earthquake — {p.get('place', 'unknown location')}",
                "summary": f"Magnitude {mag:.1f} at {g[2]:.0f} km depth."
                           + (" Tsunami advisory issued." if p.get("tsunami") else ""),
                "url": p.get("url", ""),
                "source": "usgs.gov",
                "channel": "usgs",
                "category": "hazard",
                # M4.5 → 0.25, M6 → 0.55, M7+ → 0.75+
                "severity": round(_clamp((mag - 3.0) / 5.0), 2),
                "lat": g[1], "lon": g[0],
                "place": p.get("place", ""), "country": "",
                "actors": "",
            })
        n = db.insert_events(rows)
        db.log_ingest("usgs", n)
        return n
    except Exception as e:
        log.warning("usgs failed: %s", e)
        db.log_ingest("usgs", 0, str(e))
        return 0


# ---------------------------------------------------------------- GDACS disasters

GDACS_FEED = "https://www.gdacs.org/xml/rss.xml"
GDACS_SEV = {"Green": 0.3, "Orange": 0.6, "Red": 0.9}


def ingest_gdacs() -> int:
    try:
        with httpx.Client(timeout=TIMEOUT, headers=UA, follow_redirects=True) as client:
            feed = feedparser.parse(client.get(GDACS_FEED).raise_for_status().text)
        rows = []
        for e in feed.entries:
            try:
                lat, lon = float(e.get("geo_lat")), float(e.get("geo_long"))
            except (TypeError, ValueError):
                continue
            alert = e.get("gdacs_alertlevel", "Green")
            ts = _entry_time(e)
            rows.append({
                "id": _id("gdacs", e.get("id", e.get("link", e.title))),
                "ts": ts,
                "title": e.title,
                "summary": re.sub(r"<[^>]+>", " ", e.get("summary", ""))[:500].strip(),
                "url": e.get("link", ""),
                "source": "gdacs.org",
                "channel": "gdacs",
                "category": "disaster",
                "severity": GDACS_SEV.get(alert, 0.3),
                "lat": lat, "lon": lon,
                "place": e.get("gdacs_country", ""),
                "country": e.get("gdacs_country", ""),
                "actors": "",
            })
        n = db.insert_events(rows)
        db.log_ingest("gdacs", n)
        return n
    except Exception as e:
        log.warning("gdacs failed: %s", e)
        db.log_ingest("gdacs", 0, str(e))
        return 0


# ---------------------------------------------------------------- News RSS

RSS_FEEDS = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("UN News", "https://news.un.org/feed/subscribe/en/news/all/rss.xml"),
    ("ReliefWeb", "https://reliefweb.int/updates/rss.xml"),
    ("Deutsche Welle", "https://rss.dw.com/rdf/rss-en-world"),
    ("France 24", "https://www.france24.com/en/rss"),
]

# crude category routing from headline keywords
KEYWORD_CATS = [
    ("conflict", r"\b(airstrike|strike[sd]?|attack|missile|drone|shelling|killed|offensive|"
                 r"invasion|clash|bombing|gunmen|troops kill|war\b)"),
    ("unrest", r"\b(protest|riot|demonstrat|unrest|strike action|uprising|crackdown)"),
    ("military", r"\b(military|troops|deployment|naval|exercise[s]?|mobiliz|nuclear|missile test)"),
    ("disaster", r"\b(flood|earthquake|hurricane|typhoon|cyclone|wildfire|landslide|eruption|"
                 r"famine|drought|outbreak|epidemic)"),
    ("diplomacy", r"\b(summit|sanction|talks|treaty|ceasefire|negotiat|election|diplomat|vote)"),
]
KEYWORD_CATS = [(c, re.compile(p, re.IGNORECASE)) for c, p in KEYWORD_CATS]

SEV_BASE = {"conflict": 0.55, "disaster": 0.5, "unrest": 0.45,
            "military": 0.45, "diplomacy": 0.3, "other": 0.25}


def ingest_rss() -> int:
    total = 0
    with httpx.Client(timeout=TIMEOUT, headers=UA, follow_redirects=True) as client:
        for name, url in RSS_FEEDS:
            try:
                feed = feedparser.parse(client.get(url).raise_for_status().text)
                rows = []
                for e in feed.entries[:80]:
                    title = e.get("title", "").strip()
                    if not title:
                        continue
                    summary = re.sub(r"<[^>]+>", " ", e.get("summary", "")).strip()[:500]
                    loc = geo.locate(title) or geo.locate(summary[:200])
                    if not loc:
                        continue
                    lat, lon, place, country = loc
                    category = "other"
                    for cat, pat in KEYWORD_CATS:
                        if pat.search(title):
                            category = cat
                            break
                    rows.append({
                        "id": _id("rss", e.get("link", title)),
                        "ts": _entry_time(e),
                        "title": title,
                        "summary": summary,
                        "url": e.get("link", ""),
                        "source": _domain(e.get("link", "")) or name,
                        "channel": "rss",
                        "category": category,
                        "severity": SEV_BASE[category],
                        "lat": lat, "lon": lon,
                        "place": place, "country": country,
                        "actors": "",
                    })
                total += db.insert_events(rows)
            except Exception as ex:
                log.warning("rss %s failed: %s", name, ex)
    db.log_ingest("rss", total)
    return total


def _entry_time(e) -> str:
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_all():
    ingest_usgs()
    ingest_gdacs()
    ingest_rss()
    ingest_gdelt()
    db.prune(days=14)
