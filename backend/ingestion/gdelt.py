"""
GDELT 2.0 Events ingestion.
Downloads latest 15-minute export, parses, filters for relevance, stores raw items.
"""
import csv
import io
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import httpx
from backend.db import get_conn, insert, query_one, transaction

GDELT_LASTUPDATE = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
GDELT_BASE = "http://data.gdeltproject.org/gdeltv2/"

# GDELT Events column names (from official docs)
GDELT_COLUMNS = [
    "GLOBALEVENTID", "SQLDATE", "MonthYear", "Year", "FractionDate",
    "Actor1Code", "Actor1Name", "Actor1CountryCode", "Actor1KnownGroupCode",
    "Actor1EthnicCode", "Actor1Religion1Code", "Actor1Religion2Code",
    "Actor1Type1Code", "Actor1Type2Code", "Actor1Type3Code",
    "Actor2Code", "Actor2Name", "Actor2CountryCode", "Actor2KnownGroupCode",
    "Actor2EthnicCode", "Actor2Religion1Code", "Actor2Religion2Code",
    "Actor2Type1Code", "Actor2Type2Code", "Actor2Type3Code",
    "IsRootEvent", "EventCode", "EventBaseCode", "EventRootCode",
    "QuadClass", "GoldsteinScale", "NumMentions", "NumSources", "NumArticles",
    "AvgTone", "Actor1Geo_Type", "Actor1Geo_FullName", "Actor1Geo_CountryCode",
    "Actor1Geo_ADM1Code", "Actor1Geo_Lat", "Actor1Geo_Long", "Actor1Geo_FeatureID",
    "Actor2Geo_Type", "Actor2Geo_FullName", "Actor2Geo_CountryCode",
    "Actor2Geo_ADM1Code", "Actor2Geo_Lat", "Actor2Geo_Long", "Actor2Geo_FeatureID",
    "ActionGeo_Type", "ActionGeo_FullName", "ActionGeo_CountryCode",
    "ActionGeo_ADM1Code", "ActionGeo_Lat", "ActionGeo_Long", "ActionGeo_FeatureID",
    "DATEADDED", "SOURCEURL"
]

# CAMEO Event Root Codes we care about (conflict, diplomacy, disaster)
RELEVANT_ROOT_CODES = {
    "01",  # Make public statement
    "02",  # Appeal
    "03",  # Express intent to cooperate
    "04",  # Consult
    "05",  # Engage in diplomatic cooperation
    "06",  # Engage in material cooperation
    "07",  # Provide aid
    "08",  # Yield
    "09",  # Investigate
    "10",  # Demand
    "11",  # Disapprove
    "12",  # Reject
    "13",  # Threaten
    "14",  # Protest
    "15",  # Exhibit military posture
    "16",  # Reduce relations
    "17",  # Coerce
    "18",  # Assault
    "19",  # Fight
    "20",  # Use unconventional mass violence
}

# QuadClass: 1=Verbal Cooperation, 2=Material Cooperation, 3=Verbal Conflict, 4=Material Conflict
CONFLICT_QUADCLASSES = {"3", "4"}

# Minimum mentions/sources for credibility
MIN_MENTIONS = 2
MIN_SOURCES = 1

class GDELTIngester:
    def __init__(self):
        self.client = httpx.Client(timeout=120.0, follow_redirects=True)
        self.source_id = self._ensure_source()

    def _ensure_source(self) -> int:
        """Get or create GDELT source record."""
        row = query_one("SELECT id FROM sources WHERE name = 'GDELT 2.0 Events'")
        if row:
            return row["id"]
        return insert("sources", {
            "name": "GDELT 2.0 Events",
            "type": "gdelt",
            "url": GDELT_BASE,
            "config_json": '{"feed": "events"}',
            "enabled": 1
        })

    def get_latest_export_url(self) -> Optional[str]:
        """Fetch lastupdate.txt and return the latest Events CSV ZIP URL."""
        try:
            resp = self.client.get(GDELT_LASTUPDATE)
            resp.raise_for_status()
            lines = resp.text.strip().split("\n")
            for line in lines:
                if ".export.CSV.zip" in line:
                    # Format: "size md5hash url"
                    parts = line.split()
                    if len(parts) >= 3:
                        return parts[2]
                    elif len(parts) >= 2:
                        return parts[1]  # fallback
            return None
        except Exception as e:
            print(f"[GDELT] Failed to get latest export: {e}")
            return None

    def download_and_parse(self, url: str) -> List[Dict[str, Any]]:
        """Download ZIP, parse CSV, return filtered raw items."""
        print(f"[GDELT] Downloading {url}")
        resp = self.client.get(url)
        resp.raise_for_status()

        items = []
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_name = [n for n in zf.namelist() if n.endswith(".CSV")][0]
            with zf.open(csv_name) as f:
                # GDELT uses tab-separated, no header
                text = io.TextIOWrapper(f, encoding="utf-8", errors="ignore")
                reader = csv.DictReader(text, fieldnames=GDELT_COLUMNS, delimiter="\t")
                for row in reader:
                    if self._is_relevant(row):
                        items.append(self._row_to_raw_item(row, url))
        print(f"[GDELT] Parsed {len(items)} relevant events from export")
        return items

    def _is_relevant(self, row: Dict[str, str]) -> bool:
        """Filter for events we care about."""
        root_code = row.get("EventRootCode", "")
        quad_class = row.get("QuadClass", "")
        mentions = int(row.get("NumMentions", "0") or 0)
        sources = int(row.get("NumSources", "0") or 0)

        # Must be relevant root code AND (conflict quadclass OR high mentions)
        if root_code not in RELEVANT_ROOT_CODES:
            return False
        if quad_class not in CONFLICT_QUADCLASSES and mentions < MIN_MENTIONS:
            return False
        if sources < MIN_SOURCES:
            return False

        # Must have action geo coordinates
        lat = row.get("ActionGeo_Lat", "")
        lng = row.get("ActionGeo_Long", "")
        if not lat or not lng:
            return False

        return True

    def _row_to_raw_item(self, row: Dict[str, str], source_url: str) -> Dict[str, Any]:
        """Convert GDELT row to raw_item dict."""
        event_id = row["GLOBALEVENTID"]
        date_str = row["SQLDATE"]
        try:
            published = datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            published = datetime.utcnow()

        # Build a readable title
        actor1 = row.get("Actor1Name", "Unknown")
        actor2 = row.get("Actor2Name", "")
        event_code = row.get("EventRootCode", "")
        location = row.get("ActionGeo_FullName", "")

        title_parts = [actor1]
        if actor2:
            title_parts.append(f"vs {actor2}")
        title_parts.append(f"({event_code})")
        if location:
            title_parts.append(f"@ {location}")

        return {
            "source_id": self.source_id,
            "external_id": event_id,
            "title": " ".join(title_parts),
            "url": row.get("SOURCEURL", ""),
            "published_at": published.isoformat(),
            "raw_json": json.dumps(row)
        }

    def store_raw_items(self, items: List[Dict[str, Any]]) -> int:
        """Bulk insert raw items, return count inserted."""
        if not items:
            return 0
        with transaction() as conn:
            # Update source last_fetched
            conn.execute(
                "UPDATE sources SET last_fetched = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), self.source_id)
            )
            # Insert raw items (ON CONFLICT DO NOTHING via UNIQUE constraint)
            cols = ", ".join(items[0].keys())
            placeholders = ", ".join(["?" for _ in items[0]])
            sql = f"INSERT OR IGNORE INTO raw_items ({cols}) VALUES ({placeholders})"
            conn.executemany(sql, [tuple(item.values()) for item in items])
            conn.commit()
            return conn.total_changes

    def update_source_success(self):
        with get_conn() as conn:
            conn.execute(
                "UPDATE sources SET last_success = ?, error_count = 0 WHERE id = ?",
                (datetime.utcnow().isoformat(), self.source_id)
            )
            conn.commit()

    def update_source_error(self):
        with get_conn() as conn:
            conn.execute(
                "UPDATE sources SET error_count = error_count + 1 WHERE id = ?",
                (self.source_id,)
            )
            conn.commit()

    def run_once(self) -> int:
        """Single ingestion cycle. Returns number of new raw items stored."""
        url = self.get_latest_export_url()
        if not url:
            print("[GDELT] No export URL found")
            return 0

        try:
            items = self.download_and_parse(url)
            count = self.store_raw_items(items)
            self.update_source_success()
            if count > 0:
                print(f"[GDELT] Stored {count} new raw items")
            return count
        except Exception as e:
            print(f"[GDELT] Ingestion failed: {e}")
            self.update_source_error()
            raise

import json  # moved here to avoid circular import