"""SQLite storage layer with FTS5 full-text search."""
import os
import sqlite3
import threading

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "globe.db")

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id        TEXT PRIMARY KEY,
    ts        TEXT NOT NULL,            -- ISO8601 UTC
    title     TEXT NOT NULL,
    summary   TEXT DEFAULT '',
    url       TEXT DEFAULT '',
    source    TEXT DEFAULT '',          -- domain or feed name
    channel   TEXT DEFAULT '',          -- gdelt | rss | usgs | gdacs | sample
    category  TEXT DEFAULT 'other',     -- conflict | unrest | military | diplomacy | disaster | hazard | other
    severity  REAL DEFAULT 0.3,         -- 0..1
    lat       REAL NOT NULL,
    lon       REAL NOT NULL,
    place     TEXT DEFAULT '',
    country   TEXT DEFAULT '',
    actors    TEXT DEFAULT '',
    ingested  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_cat ON events(category);
CREATE INDEX IF NOT EXISTS idx_events_url ON events(url);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    title, summary, place, actors, country,
    content='events', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, title, summary, place, actors, country)
    VALUES (new.rowid, new.title, new.summary, new.place, new.actors, new.country);
END;
CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, title, summary, place, actors, country)
    VALUES ('delete', old.rowid, old.title, old.summary, old.place, old.actors, old.country);
END;

CREATE TABLE IF NOT EXISTS ingest_log (
    channel TEXT PRIMARY KEY,
    last_run TEXT,
    last_count INTEGER DEFAULT 0,
    last_error TEXT DEFAULT ''
);
"""


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        _local.conn = conn
    return conn


def insert_events(rows: list[dict]) -> int:
    """Insert events, skipping ids and urls already present. Returns inserted count."""
    if not rows:
        return 0
    conn = get_conn()
    inserted = 0
    with conn:
        for r in rows:
            if r.get("url"):
                dup = conn.execute(
                    "SELECT 1 FROM events WHERE url = ? AND id != ? LIMIT 1",
                    (r["url"], r["id"]),
                ).fetchone()
                if dup:
                    continue
            cur = conn.execute(
                """INSERT OR IGNORE INTO events
                   (id, ts, title, summary, url, source, channel, category,
                    severity, lat, lon, place, country, actors)
                   VALUES (:id,:ts,:title,:summary,:url,:source,:channel,:category,
                           :severity,:lat,:lon,:place,:country,:actors)""",
                r,
            )
            inserted += cur.rowcount
    return inserted


def log_ingest(channel: str, count: int, error: str = ""):
    conn = get_conn()
    with conn:
        conn.execute(
            """INSERT INTO ingest_log(channel, last_run, last_count, last_error)
               VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ','now'), ?, ?)
               ON CONFLICT(channel) DO UPDATE SET
                 last_run=excluded.last_run, last_count=excluded.last_count,
                 last_error=excluded.last_error""",
            (channel, count, error),
        )


def query_events(since_hours: int = 72, category: str = "", min_severity: float = 0.0,
                 q: str = "", limit: int = 1000) -> list[dict]:
    conn = get_conn()
    params: list = []
    if q:
        sql = """SELECT e.* FROM events e
                 JOIN events_fts f ON f.rowid = e.rowid
                 WHERE events_fts MATCH ?"""
        # FTS5 prefix query; quote to survive punctuation in user input
        params.append('"' + q.replace('"', "") + '"*')
    else:
        sql = "SELECT e.* FROM events e WHERE 1=1"
    sql += " AND e.ts >= strftime('%Y-%m-%dT%H:%M:%SZ','now', ?)"
    params.append(f"-{int(since_hours)} hours")
    if category:
        cats = [c.strip() for c in category.split(",") if c.strip()]
        sql += " AND e.category IN (%s)" % ",".join("?" * len(cats))
        params.extend(cats)
    if min_severity > 0:
        sql += " AND e.severity >= ?"
        params.append(min_severity)
    sql += " ORDER BY e.ts DESC LIMIT ?"
    params.append(min(int(limit), 5000))
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_event(event_id: str) -> dict | None:
    row = get_conn().execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return dict(row) if row else None


def stats() -> dict:
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
    last24 = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE ts >= strftime('%Y-%m-%dT%H:%M:%SZ','now','-24 hours')"
    ).fetchone()["c"]
    by_cat = {
        r["category"]: r["c"]
        for r in conn.execute(
            """SELECT category, COUNT(*) c FROM events
               WHERE ts >= strftime('%Y-%m-%dT%H:%M:%SZ','now','-72 hours')
               GROUP BY category"""
        )
    }
    ingest = [dict(r) for r in conn.execute("SELECT * FROM ingest_log")]
    return {"total": total, "last24h": last24, "by_category_72h": by_cat, "ingest": ingest}


def prune(days: int = 14):
    conn = get_conn()
    with conn:
        conn.execute(
            "DELETE FROM events WHERE ts < strftime('%Y-%m-%dT%H:%M:%SZ','now', ?)",
            (f"-{int(days)} days",),
        )
