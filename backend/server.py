"""FastAPI app: JSON API + static frontend on a single port."""
import logging
import os
import threading
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db, ingest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_INGEST = os.environ.get("GLOBE_NO_INGEST") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.get_conn()
    scheduler = None
    if not NO_INGEST:
        # first ingest in a daemon thread so startup isn't blocked
        threading.Thread(target=ingest.run_all, daemon=True).start()
        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(ingest.ingest_gdelt, "interval", minutes=15)
        scheduler.add_job(ingest.ingest_rss, "interval", minutes=10)
        scheduler.add_job(ingest.ingest_usgs, "interval", minutes=15)
        scheduler.add_job(ingest.ingest_gdacs, "interval", minutes=20)
        scheduler.add_job(db.prune, "interval", hours=6)
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="globe", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/events")
def events(
    since_hours: int = Query(72, ge=1, le=336),
    category: str = "",
    min_severity: float = Query(0.0, ge=0.0, le=1.0),
    q: str = "",
    limit: int = Query(1200, ge=1, le=5000),
):
    return {"events": db.query_events(since_hours, category, min_severity, q, limit)}


@app.get("/api/events/{event_id}")
def event(event_id: str):
    return db.get_event(event_id) or {"error": "not found"}


@app.get("/api/stats")
def stats():
    return db.stats()


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")
app.mount("/data", StaticFiles(directory=os.path.join(ROOT, "data")), name="data")
