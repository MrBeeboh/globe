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

from . import cctv, db, ingest, intel, osint, plugins, recon, schedule

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_INGEST = os.environ.get("GLOBE_NO_INGEST") == "1"
_refresh_lock = threading.Lock()
_scheduler: BackgroundScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    db.get_conn()
    if not NO_INGEST:
        threading.Thread(target=ingest.run_all, daemon=True).start()
        _scheduler = BackgroundScheduler(timezone="UTC")
        schedule.register_jobs(_scheduler)
        _scheduler.add_job(db.prune, "interval", hours=6, id="prune")
        _scheduler.add_job(intel.refresh_all, "interval", minutes=3, id="intel_refresh")
        threading.Thread(target=intel.refresh_all, daemon=True).start()
        _scheduler.start()
        app.state.scheduler = _scheduler
    else:
        app.state.scheduler = None
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


app = FastAPI(title="Globe — Open Geospatial Intelligence", lifespan=lifespan)


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


@app.get("/api/plugins")
def plugin_registry():
    return plugins.get_registry(ROOT)


@app.get("/api/intel/{kind}")
def intel_feed(kind: str):
    if kind not in ("flights", "satellites", "fires", "vessels"):
        return {"error": "unknown kind", "items": []}
    return intel.get_intel(kind)


class GeocodeRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


@app.post("/api/osint/geocode")
def osint_geocode(body: GeocodeRequest):
    return osint.reverse_geocode(body.lat, body.lon)


@app.get("/api/cctv")
def cctv_feeds():
    return cctv.get_feeds(ROOT)


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


class ScheduleUpdate(BaseModel):
    preset: str | None = None
    rss: int | None = Field(None, ge=5, le=120)
    gdelt: int | None = Field(None, ge=5, le=120)
    usgs: int | None = Field(None, ge=5, le=120)
    gdacs: int | None = Field(None, ge=5, le=120)


@app.get("/api/schedule")
def get_schedule():
    sched = getattr(app.state, "scheduler", None)
    return schedule.status(sched)


@app.patch("/api/schedule")
def patch_schedule(body: ScheduleUpdate):
    if NO_INGEST:
        return {"ok": False, "error": "ingest disabled (GLOBE_NO_INGEST=1)"}
    sched = getattr(app.state, "scheduler", None)
    if not sched:
        return {"ok": False, "error": "scheduler not running"}
    try:
        if body.preset:
            intervals = schedule.apply_preset(body.preset)
        else:
            patch = {k: v for k, v in body.model_dump().items() if v is not None and k != "preset"}
            intervals = schedule.apply_intervals(patch) if patch else schedule.load()
        schedule.register_jobs(sched, intervals)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, **schedule.status(sched)}


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