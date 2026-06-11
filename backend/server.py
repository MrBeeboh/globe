"""
FastAPI server for World Event Globe.
Endpoints: /events, /countries, /cities, /search, /stats
"""
import json
from datetime import datetime, timedelta
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.db import get_conn, query, query_one, init_db
from backend.ingestion.scheduler import IngestionScheduler
from backend.ingestion.countries import CountryIngester
from backend.ingestion.cities import upsert_cities

# Global scheduler instance
scheduler: Optional[IngestionScheduler] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    init_db()

    # Ensure country profiles are loaded (runs once, idempotent)
    print("[API] Loading country profiles...")
    try:
        CountryIngester().run_all()
        print("[API] Countries loaded")
    except Exception as e:
        print(f"[API] Country load failed (non-fatal): {e}")

    # Ensure city profiles are loaded
    print("[API] Loading city profiles...")
    try:
        upsert_cities()
        print("[API] Cities loaded")
    except Exception as e:
        print(f"[API] City load failed (non-fatal): {e}")

    scheduler = IngestionScheduler()
    scheduler.start()
    print("[API] Server started with scheduler")
    yield
    if scheduler:
        scheduler.stop()
    print("[API] Server stopped")

app = FastAPI(
    title="World Event Globe API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models ---

class EventResponse(BaseModel):
    id: int
    title: str
    summary: Optional[str]
    url: Optional[str]
    category: str
    severity: int
    confidence: float
    lat: Optional[float]
    lng: Optional[float]
    location_name: str
    country_code: Optional[str]
    region: str
    actors: List[dict]
    casualties: dict
    tags: List[str]
    published_at: str

class CountryResponse(BaseModel):
    iso3: str
    name: str
    capital: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    population: Optional[int]
    area_km2: Optional[int]
    gdp_usd: Optional[int]
    gdp_per_capita: Optional[int]
    regime_type: Optional[str]
    regime_score: Optional[float]
    military_spending_usd: Optional[int]
    military_personnel: Optional[int]
    nuclear: int
    trade_partners: List[dict]
    risk_indices: dict
    leadership: dict
    recent_coups: int
    recent_protests: int
    conflict_history: dict

class CityResponse(BaseModel):
    id: int
    name: str
    country_code: str
    lat: float
    lng: float
    population: Optional[int]
    metro_population: Optional[int]
    strategic_value: Optional[str]
    infrastructure: dict
    recent_events_count: int

class StatsResponse(BaseModel):
    total_events: int
    events_24h: int
    events_7d: int
    by_category: dict
    by_region: dict
    by_severity: dict
    sources: List[dict]
    last_updated: str

# --- Helper Functions ---

def row_to_event(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "summary": row["summary"],
        "url": row["url"],
        "category": row["category"],
        "severity": row["severity"],
        "confidence": row["confidence"],
        "lat": row["lat"],
        "lng": row["lng"],
        "location_name": row["location_name"],
        "country_code": row["country_code"],
        "region": row["region"],
        "actors": json.loads(row["actors_json"]) if row["actors_json"] else [],
        "casualties": json.loads(row["casualties_json"]) if row["casualties_json"] else {},
        "tags": json.loads(row["tags_json"]) if row["tags_json"] else [],
        "published_at": row["published_at"]
    }

def row_to_country(row) -> dict:
    return {
        "iso3": row["iso3"],
        "name": row["name"],
        "capital": row["capital"],
        "lat": row["lat"],
        "lng": row["lng"],
        "population": row["population"],
        "area_km2": row["area_km2"],
        "gdp_usd": row["gdp_usd"],
        "gdp_per_capita": row["gdp_per_capita"],
        "regime_type": row["regime_type"],
        "regime_score": row["regime_score"],
        "military_spending_usd": row["military_spending_usd"],
        "military_personnel": row["military_personnel"],
        "nuclear": row["nuclear"],
        "trade_partners": json.loads(row["trade_partners_json"]) if row["trade_partners_json"] else [],
        "risk_indices": json.loads(row["risk_indices_json"]) if row["risk_indices_json"] else {},
        "leadership": json.loads(row["leadership_json"]) if row["leadership_json"] else {},
        "recent_coups": row["recent_coups"],
        "recent_protests": row["recent_protests"],
        "conflict_history": json.loads(row["conflict_history_json"]) if row["conflict_history_json"] else {}
    }

# --- Endpoints ---

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/events", response_model=List[EventResponse])
async def get_events(
    category: Optional[str] = Query(None, description="Filter by category"),
    region: Optional[str] = Query(None, description="Filter by region"),
    country: Optional[str] = Query(None, description="Filter by country ISO3"),
    min_severity: int = Query(0, ge=0, le=100, description="Minimum severity"),
    max_severity: int = Query(100, ge=0, le=100, description="Maximum severity"),
    since_hours: int = Query(168, ge=1, le=8760, description="Hours back to search"),
    limit: int = Query(500, ge=1, le=2000, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    search: Optional[str] = Query(None, description="Full-text search query")
):
    """Get events with filters."""
    conditions = ["published_at > datetime('now', ?)"]
    params = [f"-{since_hours} hours"]

    if category:
        conditions.append("category = ?")
        params.append(category)
    if region:
        conditions.append("region = ?")
        params.append(region)
    if country:
        conditions.append("country_code = ?")
        params.append(country.upper())
    if min_severity > 0:
        conditions.append("severity >= ?")
        params.append(min_severity)
    if max_severity < 100:
        conditions.append("severity <= ?")
        params.append(max_severity)

    where_clause = " WHERE " + " AND ".join(conditions)

    if search:
        # Use FTS5
        sql = f"""
            SELECT e.* FROM events e
            JOIN events_fts fts ON e.id = fts.rowid
            {where_clause}
            AND events_fts MATCH ?
            ORDER BY e.published_at DESC
            LIMIT ? OFFSET ?
        """
        params.append(search)
        params.extend([limit, offset])
    else:
        sql = f"""
            SELECT * FROM events
            {where_clause}
            ORDER BY published_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

    rows = query(sql, tuple(params))
    return [row_to_event(r) for r in rows]

@app.get("/events/{event_id}/related")
async def get_related_events(
    event_id: int,
    limit: int = Query(5, ge=1, le=20)
):
    """Find related events by country, region, or category."""
    event = query_one("SELECT * FROM events WHERE id = ?", (event_id,))
    if not event:
        raise HTTPException(404, "Event not found")

    # Find related: same country, same region, or same category
    related = query("""
        SELECT e.* FROM events e WHERE e.id != ?
        AND (
            e.country_code = ?
            OR (e.region = ? AND e.region != 'Unknown')
            OR (e.category = ? AND e.confidence > 0.4)
        )
        ORDER BY e.severity DESC, e.published_at DESC
        LIMIT ?
    """, (event_id, event["country_code"] or "", event["region"], event["category"], limit))

    return [row_to_event(r) for r in related]


@app.get("/events/{event_id}", response_model=EventResponse)
async def get_event(event_id: int):
    """Get single event by ID with entities."""
    row = query_one("SELECT * FROM events WHERE id = ?", (event_id,))
    if not row:
        raise HTTPException(404, "Event not found")

    event = row_to_event(row)

    # Add related entities
    entities = query("""
        SELECT entity_type, name, aliases_json, metadata_json, mention_count
        FROM entities WHERE event_id = ?
    """, (event_id,))
    event["entities"] = [
        {
            "type": e["entity_type"],
            "name": e["name"],
            "aliases": json.loads(e["aliases_json"]),
            "metadata": json.loads(e["metadata_json"]),
            "mentions": e["mention_count"]
        }
        for e in entities
    ]

    return event

@app.get("/search")
async def search_events(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(50, ge=1, le=200)
):
    """Full-text search across events."""
    rows = query("""
        SELECT e.*, rank
        FROM events e
        JOIN events_fts fts ON e.id = fts.rowid
        WHERE events_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """, (q, limit))
    return [row_to_event(r) for r in rows]

@app.get("/countries", response_model=List[CountryResponse])
async def get_countries(
    region: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500)
):
    """Get all country profiles."""
    sql = "SELECT * FROM countries"
    params = []
    if region:
        # Would need region column on countries table - for now filter in Python
        pass
    sql += " LIMIT ?"
    params.append(limit)
    rows = query(sql, tuple(params))
    return [row_to_country(r) for r in rows]

@app.get("/countries/{iso3}", response_model=CountryResponse)
async def get_country(iso3: str):
    """Get detailed country profile."""
    row = query_one("SELECT * FROM countries WHERE iso3 = ?", (iso3.upper(),))
    if not row:
        raise HTTPException(404, "Country not found")
    return row_to_country(row)

@app.get("/countries/{iso3}/events", response_model=List[EventResponse])
async def get_country_events(
    iso3: str,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(200, ge=1, le=1000)
):
    """Get events for a specific country."""
    rows = query("""
        SELECT e.* FROM events e
        JOIN event_countries ec ON e.id = ec.event_id
        WHERE ec.country_code = ? AND e.published_at > datetime('now', ?)
        ORDER BY e.severity DESC, e.published_at DESC
        LIMIT ?
    """, (iso3.upper(), f"-{days} days", limit))
    return [row_to_event(r) for r in rows]

@app.get("/cities", response_model=List[CityResponse])
async def get_cities(
    country: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=2000)
):
    """Get city profiles."""
    sql = "SELECT * FROM cities"
    params = []
    if country:
        sql += " WHERE country_code = ?"
        params.append(country.upper())
    sql += " LIMIT ?"
    params.append(limit)
    rows = query(sql, tuple(params))
    return [dict(r) for r in rows]

@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get dashboard statistics."""
    total = query_one("SELECT COUNT(*) as c FROM events")["c"]
    events_24h = query_one("SELECT COUNT(*) as c FROM events WHERE published_at > datetime('now', '-24 hours')")["c"]
    events_7d = query_one("SELECT COUNT(*) as c FROM events WHERE published_at > datetime('now', '-7 days')")["c"]

    by_cat = query("SELECT category, COUNT(*) as c FROM events GROUP BY category")
    by_reg = query("SELECT region, COUNT(*) as c FROM events GROUP BY region")
    by_sev = query("""
        SELECT
            CASE
                WHEN severity >= 70 THEN 'critical'
                WHEN severity >= 50 THEN 'high'
                WHEN severity >= 30 THEN 'medium'
                ELSE 'low'
            END as level,
            COUNT(*) as c
        FROM events GROUP BY level
    """)

    sources = query("""
        SELECT name, type, enabled, last_fetched, last_success, error_count,
               (SELECT COUNT(*) FROM raw_items WHERE source_id = s.id) as total_raw,
               (SELECT COUNT(*) FROM events e JOIN raw_items ri ON e.raw_item_id = ri.id WHERE ri.source_id = s.id) as total_events
        FROM sources s ORDER BY total_events DESC
    """)

    return {
        "total_events": total,
        "events_24h": events_24h,
        "events_7d": events_7d,
        "by_category": {r["category"]: r["c"] for r in by_cat},
        "by_region": {r["region"]: r["c"] for r in by_reg},
        "by_severity": {r["level"]: r["c"] for r in by_sev},
        "sources": [dict(r) for r in sources],
        "last_updated": datetime.utcnow().isoformat()
    }

@app.post("/admin/trigger/{job}")
async def trigger_job(job: str):
    """Manually trigger ingestion jobs."""
    if not scheduler:
        raise HTTPException(503, "Scheduler not running")

    if job == "gdelt":
        scheduler.run_gdelt()
        return {"triggered": "gdelt"}
    elif job == "rss":
        scheduler.run_rss()
        return {"triggered": "rss"}
    elif job == "enrich":
        scheduler.run_enrichment(limit=500)
        return {"triggered": "enrich"}
    elif job == "maintenance":
        scheduler.run_maintenance()
        return {"triggered": "maintenance"}
    else:
        raise HTTPException(404, f"Unknown job: {job}")

@app.get("/admin/status")
async def admin_status():
    """Scheduler and system status."""
    if not scheduler:
        return {"scheduler": "stopped"}

    jobs = []
    for job in scheduler.scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger)
        })

    # DB stats
    db_stats = {}
    for table in ["events", "raw_items", "sources", "entities", "countries", "cities"]:
        row = query_one(f"SELECT COUNT(*) as c FROM {table}")
        db_stats[table] = row["c"]

    return {
        "scheduler": "running" if scheduler.running else "stopped",
        "jobs": jobs,
        "database": db_stats
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8091)