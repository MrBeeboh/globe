"""
RSS feed ingestion for major conflict/geopolitics news sources.
"""
import feedparser
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional
import httpx
from backend.db import get_conn, insert, query_one, query, transaction

# Curated high-signal RSS feeds for conflict, geopolitics, disasters
RSS_FEEDS = [
    # Major wire services
    {"name": "Reuters World", "url": "https://feeds.reuters.com/reuters/worldNews", "category": "general"},
    {"name": "AP News World", "url": "https://apnews.com/hub/world-news", "category": "general"},
    {"name": "AFP", "url": "https://www.afp.com/en/rss-feed", "category": "general"},

    # Conflict & security specialized
    {"name": "War on the Rocks", "url": "https://warontherocks.com/feed/", "category": "security"},
    {"name": "The Drive - War Zone", "url": "https://www.thedrive.com/the-war-zone/rss", "category": "security"},
    {"name": "Defense One", "url": "https://www.defenseone.com/rss/", "category": "security"},
    {"name": "IISS", "url": "https://www.iiss.org/rss.xml", "category": "security"},

    # Regional - Middle East
    {"name": "Al Jazeera English", "url": "https://www.aljazeera.com/xml/rss/all.xml", "category": "meast"},
    {"name": "Times of Israel", "url": "https://www.timesofisrael.com/feed/", "category": "meast"},
    {"name": "Haaretz", "url": "https://www.haaretz.com/cmlink/1.1234567", "category": "meast"},

    # Regional - Asia
    {"name": "South China Morning Post", "url": "https://www.scmp.com/rss/91/feed", "category": "asia"},
    {"name": "The Hindu", "url": "https://www.thehindu.com/news/international/feeder/default.rss", "category": "asia"},
    {"name": "Japan Times", "url": "https://www.japantimes.co.jp/feed/", "category": "asia"},

    # Regional - Europe/Russia
    {"name": "Meduza English", "url": "https://meduza.io/en/rss", "category": "europe"},
    {"name": "Euractiv", "url": "https://www.euractiv.com/feed/", "category": "europe"},
    {"name": "EU Observer", "url": "https://euobserver.com/rss", "category": "europe"},

    # Humanitarian / Disasters
    {"name": "ReliefWeb", "url": "https://reliefweb.int/updates/rss.xml", "category": "humanitarian"},
    {"name": "OCHA", "url": "https://www.unocha.org/feeds/rss.xml", "category": "humanitarian"},
    {"name": "GDACS", "url": "https://www.gdacs.org/rss.xml", "category": "disaster"},

    # Intelligence / Analysis
    {"name": "Stratfor (RSI)", "url": "https://worldview.stratfor.com/rss.xml", "category": "analysis"},
    {"name": "Geopolitical Monitor", "url": "https://www.geopoliticalmonitor.com/feed/", "category": "analysis"},
    {"name": "Carnegie Endowment", "url": "https://carnegieendowment.org/rss.xml", "category": "analysis"},
]

class RSSEnginer:
    def __init__(self):
        self.client = httpx.Client(timeout=30.0, follow_redirects=True, headers={
            "User-Agent": "WorldEventGlobe/1.0 (+https://github.com/)"
        })

    def _ensure_source(self, feed: Dict[str, str]) -> int:
        row = query_one("SELECT id FROM sources WHERE name = ?", (feed["name"],))
        if row:
            return row["id"]
        return insert("sources", {
            "name": feed["name"],
            "type": "rss",
            "url": feed["url"],
            "config_json": json.dumps({"category": feed["category"]}),
            "enabled": 1
        })

    def _entry_hash(self, entry: feedparser.FeedParserDict) -> str:
        """Generate stable hash for deduplication."""
        # Use guid if available, else link, else title+date
        guid = entry.get("guid") or entry.get("id") or entry.get("link") or ""
        content = f"{guid}{entry.get('title', '')}{entry.get('published', '')}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _parse_datetime(self, entry: feedparser.FeedParserDict) -> Optional[datetime]:
        for key in ("published_parsed", "updated_parsed", "created_parsed"):
            if entry.get(key):
                try:
                    return datetime(*entry[key][:6])
                except Exception:
                    pass
        # Fallback to string parsing
        for key in ("published", "updated", "created"):
            val = entry.get(key)
            if val:
                for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return datetime.strptime(val, fmt)
                    except ValueError:
                        pass
        return datetime.utcnow()

    def fetch_feed(self, feed: Dict[str, str]) -> List[Dict[str, Any]]:
        """Fetch and parse a single RSS feed."""
        source_id = self._ensure_source(feed)
        print(f"[RSS] Fetching {feed['name']}...")

        try:
            resp = self.client.get(feed["url"])
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)

            items = []
            for entry in parsed.entries[:50]:  # Limit per feed per run
                ext_id = self._entry_hash(entry)
                # Check if already ingested
                existing = query_one(
                    "SELECT 1 FROM raw_items WHERE source_id = ? AND external_id = ?",
                    (source_id, ext_id)
                )
                if existing:
                    continue

                published = self._parse_datetime(entry)
                title = entry.get("title", "").strip()
                summary = entry.get("summary", "") or entry.get("description", "")
                link = entry.get("link", "")

                if not title or len(title) < 10:
                    continue

                items.append({
                    "source_id": source_id,
                    "external_id": ext_id,
                    "title": title,
                    "url": link,
                    "published_at": published.isoformat(),
                    "raw_json": json.dumps({
                        "title": title,
                        "summary": summary,
                        "link": link,
                        "tags": [t.term for t in entry.get("tags", [])],
                        "author": entry.get("author", "")
                    })
                })

            print(f"[RSS] {feed['name']}: {len(items)} new items")
            return items

        except Exception as e:
            print(f"[RSS] {feed['name']} failed: {e}")
            with get_conn() as conn:
                conn.execute(
                    "UPDATE sources SET error_count = error_count + 1 WHERE id = ?",
                    (source_id,)
                )
                conn.commit()
            return []

    def run_all(self) -> int:
        """Fetch all feeds, return total new items."""
        total = 0
        for feed in RSS_FEEDS:
            items = self.fetch_feed(feed)
            if items:
                with transaction() as conn:
                    cols = ", ".join(items[0].keys())
                    placeholders = ", ".join(["?" for _ in items[0]])
                    sql = f"INSERT OR IGNORE INTO raw_items ({cols}) VALUES ({placeholders})"
                    conn.executemany(sql, [tuple(item.values()) for item in items])
                    conn.commit()
                    total += conn.total_changes
            # Update source last_success
            source_id = self._ensure_source(feed)
            with get_conn() as conn:
                conn.execute(
                    "UPDATE sources SET last_fetched = ?, last_success = ? WHERE id = ?",
                    (datetime.utcnow().isoformat(), datetime.utcnow().isoformat(), source_id)
                )
                conn.commit()
        return total

import json