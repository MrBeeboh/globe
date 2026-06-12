"""FastAPI app: JSON API + static frontend on a single port."""
import logging
import os
import threading
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field

from . import db, ingest, intel, recon

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_INGEST = os.environ.get("GLOBE_NO_INGEST") == "1"
_refresh_lock = threading.Lock()


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
        scheduler.add_job(intel.refresh_all, "interval", minutes=3)
        threading.Thread(target=intel.refresh_all, daemon=True).start()
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


@app.get("/api/events/{event_id}/related")
def event_related(event_id: str, limit: int = Query(8, ge=1, le=20)):
    return {"related": db.related_events(event_id, limit)}


@app.get("/api/intel/{kind}")
def intel_feed(kind: str):
    if kind not in ("flights", "satellites", "fires"):
        return {"error": "unknown kind", "items": []}
    return intel.get_intel(kind)


@app.get("/api/cctv")
def cctv_feeds():
    import json
    path = os.path.join(ROOT, "data", "cctv-feeds.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/youtube")
def youtube_streams():
    import json
    path = os.path.join(ROOT, "data", "youtube-streams.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class ReconRequest(BaseModel):
    host: str = Field(..., min_length=1, max_length=253)
    action: str = "dns"


@app.post("/api/recon")
def recon_scan(body: ReconRequest):
    return recon.run_recon(body.host, body.action)


@app.get("/api/stats")
def stats():
    return db.stats()


@app.post("/api/refresh")
def force_refresh():
    """Pull all feeds immediately (GDELT, USGS, GDACS, RSS)."""
    if NO_INGEST:
        return {"ok": False, "error": "ingest disabled (GLOBE_NO_INGEST=1)"}
    if not _refresh_lock.acquire(blocking=False):
        return {"ok": False, "status": "busy", "error": "refresh already in progress"}
    def _run():
        try:
            ingest.run_all()
        finally:
            _refresh_lock.release()
    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "status": "started"}


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")
app.mount("/data", StaticFiles(directory=os.path.join(ROOT, "data")), name="data")
