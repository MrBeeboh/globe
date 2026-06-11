"""
Database layer for World Event Globe.
SQLite with FTS5 for full-text search on events.
"""
import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = Path(__file__).parent.parent / "data" / "globe.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-32768;
PRAGMA temp_store=memory;
PRAGMA mmap_size=268435456;

-- Sources: RSS feeds, APIs, GDELT
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,           -- 'rss', 'gdelt', 'api', 'manual'
    url TEXT,
    config_json TEXT,             -- JSON config (feed URL, API key ref, etc.)
    enabled INTEGER DEFAULT 1,
    last_fetched DATETIME,
    last_success DATETIME,
    error_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Raw ingested items before enrichment
CREATE TABLE IF NOT EXISTS raw_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    external_id TEXT,             -- GDELT event ID, RSS guid, etc.
    title TEXT,
    url TEXT,
    published_at DATETIME,
    raw_json TEXT NOT NULL,       -- Full raw payload
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_id, external_id)
);

-- Enriched events (the main query target)
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_item_id INTEGER REFERENCES raw_items(id),
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    category TEXT NOT NULL,       -- 'conflict', 'diplomatic', 'humanitarian', 'political', 'disaster', 'economic'
    severity INTEGER NOT NULL,    -- 0-100
    confidence REAL DEFAULT 0.5,  -- 0.0-1.0 enrichment confidence
    lat REAL,                     -- Event latitude
    lng REAL,                     -- Event longitude
    location_name TEXT,           -- Human-readable location
    country_code TEXT,            -- ISO3
    region TEXT,                  -- 'Middle East', 'Europe', etc.
    actors_json TEXT,             -- JSON array: [{"name": "IDF", "type": "state"}, ...]
    casualties_json TEXT,         -- JSON: {"killed": 12, "wounded": 45, "civilian": 8}
    tags_json TEXT,               -- JSON array: ["airstrike", "ceasefire", "gaza"]
    published_at DATETIME NOT NULL,
    ingested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Entity extraction: people, orgs, locations, weapons, treaties
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,    -- 'person', 'org', 'location', 'weapon', 'treaty', 'facility'
    name TEXT NOT NULL,
    aliases_json TEXT,            -- JSON array of known aliases
    metadata_json TEXT,           -- JSON: role, affiliation, etc.
    mention_count INTEGER DEFAULT 1
);

-- Country profiles (deep-dive)
CREATE TABLE IF NOT EXISTS countries (
    iso3 TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    capital TEXT,
    lat REAL,
    lng REAL,
    population INTEGER,
    area_km2 INTEGER,
    gdp_usd BIGINT,
    gdp_per_capita INTEGER,
    regime_type TEXT,             -- 'democracy', 'autocracy', 'hybrid', 'failed'
    regime_score REAL,            -- V-Dem polyarchy index 0-1
    military_spending_usd BIGINT,
    military_personnel INTEGER,
    nuclear INTEGER DEFAULT 0,
    trade_partners_json TEXT,     -- JSON: [{"country": "USA", "pct": 15.2}, ...]
    risk_indices_json TEXT,       -- JSON: {"fragile_states": 85, "conflict_risk": 70}
    leadership_json TEXT,         -- JSON: {"head_of_state": "...", "since": "..."}
    recent_coups INTEGER DEFAULT 0,
    recent_protests INTEGER DEFAULT 0,
    conflict_history_json TEXT,   -- JSON summary of major conflicts
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- City profiles
CREATE TABLE IF NOT EXISTS cities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    country_code TEXT REFERENCES countries(iso3),
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    population INTEGER,
    metro_population INTEGER,
    strategic_value TEXT,         -- 'capital', 'port', 'industrial', 'military', 'tech', 'financial'
    infrastructure_json TEXT,     -- JSON: airports, ports, bases, fiber
    recent_events_count INTEGER DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, country_code)
);

-- Event-country relations (many-to-many for multi-country events)
CREATE TABLE IF NOT EXISTS event_countries (
    event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
    country_code TEXT REFERENCES countries(iso3),
    role TEXT,                    -- 'primary', 'actor', 'target', 'mediator'
    PRIMARY KEY (event_id, country_code, role)
);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    title, summary, location_name, actors_json, tags_json,
    content='events', content_rowid='id'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, title, summary, location_name, actors_json, tags_json)
    VALUES (new.id, new.title, new.summary, new.location_name, new.actors_json, new.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, title, summary, location_name, actors_json, tags_json)
    VALUES ('delete', old.id, old.title, old.summary, old.location_name, old.actors_json, old.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, title, summary, location_name, actors_json, tags_json)
    VALUES ('delete', old.id, old.title, old.summary, old.location_name, old.actors_json, old.tags_json);
    INSERT INTO events_fts(rowid, title, summary, location_name, actors_json, tags_json)
    VALUES (new.id, new.title, new.summary, new.location_name, new.actors_json, new.tags_json);
END;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_events_published ON events(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);
CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity DESC);
CREATE INDEX IF NOT EXISTS idx_events_country ON events(country_code);
CREATE INDEX IF NOT EXISTS idx_events_region ON events(region);
CREATE INDEX IF NOT EXISTS idx_events_lat_lng ON events(lat, lng);
CREATE INDEX IF NOT EXISTS idx_raw_items_source ON raw_items(source_id, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_entities_event ON entities(event_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_cities_country ON cities(country_code);
"""

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    """Initialize database schema."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.commit()

@contextmanager
def transaction():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# --- Helpers ---

def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur

def query(sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(sql, params).fetchall()

def query_one(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(sql, params).fetchone()

def insert(table: str, data: Dict[str, Any]) -> int:
    """Insert row, return rowid."""
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?" for _ in data])
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
    with get_conn() as conn:
        cur = conn.execute(sql, tuple(data.values()))
        conn.commit()
        return cur.lastrowid

def upsert(table: str, data: Dict[str, Any], conflict_cols: List[str]) -> int:
    """Upsert row (INSERT OR REPLACE)."""
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?" for _ in data])
    conflict = ", ".join(conflict_cols)
    updates = ", ".join([f"{c}=excluded.{c}" for c in data.keys() if c not in conflict_cols])
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT({conflict}) DO UPDATE SET {updates}"
    with get_conn() as conn:
        cur = conn.execute(sql, tuple(data.values()))
        conn.commit()
        return cur.lastrowid

def bulk_insert(table: str, rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    cols = ", ".join(rows[0].keys())
    placeholders = ", ".join(["?" for _ in rows[0]])
    sql = f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})"
    with get_conn() as conn:
        conn.executemany(sql, [tuple(r.values()) for r in rows])
        conn.commit()
        return conn.total_changes