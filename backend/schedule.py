"""Ingest scheduler intervals — env defaults, JSON persistence, APScheduler wiring."""
import json
import logging
import os
from typing import Any

log = logging.getLogger("schedule")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "data", "schedule.json")

CHANNELS = ("rss", "gdelt", "usgs", "gdacs")
JOB_IDS = {ch: f"ingest_{ch}" for ch in CHANNELS}

PRESETS = {
    "fast": {"rss": 5, "gdelt": 5, "usgs": 5, "gdacs": 10},
    "normal": {"rss": 10, "gdelt": 15, "usgs": 15, "gdacs": 20},
    "slow": {"rss": 20, "gdelt": 30, "usgs": 30, "gdacs": 45},
}

DEFAULTS = {
    ch: int(os.environ.get(f"GLOBE_INGEST_{ch.upper()}_MIN", str(PRESETS["normal"][ch])))
    for ch in CHANNELS
}

_MIN, _MAX = 5, 120


def _clamp_minutes(n: int) -> int:
    return max(_MIN, min(_MAX, int(n)))


def load() -> dict[str, int]:
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            return {ch: _clamp_minutes(raw.get(ch, DEFAULTS[ch])) for ch in CHANNELS}
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as e:
            log.warning("schedule config unreadable: %s", e)
    return dict(DEFAULTS)


def save(intervals: dict[str, int]) -> dict[str, int]:
    cleaned = {ch: _clamp_minutes(intervals.get(ch, DEFAULTS[ch])) for ch in CHANNELS}
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2)
    return cleaned


def preset_name(intervals: dict[str, int]) -> str | None:
    for name, preset in PRESETS.items():
        if all(intervals[ch] == preset[ch] for ch in CHANNELS):
            return name
    return "custom"


def status(scheduler: Any | None = None) -> dict:
    intervals = load()
    jobs = {}
    if scheduler:
        for ch in CHANNELS:
            job = scheduler.get_job(JOB_IDS[ch])
            if job and job.next_run_time:
                jobs[ch] = job.next_run_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "intervals": intervals,
        "preset": preset_name(intervals),
        "presets": PRESETS,
        "limits": {"min": _MIN, "max": _MAX},
        "next_run": jobs,
    }


def register_jobs(scheduler: Any, intervals: dict[str, int] | None = None) -> dict[str, int]:
    """Add or reschedule ingest jobs on the given scheduler."""
    from . import ingest

    iv = intervals or load()
    handlers = {
        "rss": ingest.ingest_rss,
        "gdelt": ingest.ingest_gdelt,
        "usgs": ingest.ingest_usgs,
        "gdacs": ingest.ingest_gdacs,
    }
    for ch in CHANNELS:
        mins = _clamp_minutes(iv[ch])
        jid = JOB_IDS[ch]
        if scheduler.get_job(jid):
            scheduler.reschedule_job(jid, trigger="interval", minutes=mins)
        else:
            scheduler.add_job(handlers[ch], "interval", minutes=mins, id=jid, replace_existing=True)
    return {ch: _clamp_minutes(iv[ch]) for ch in CHANNELS}


def apply_preset(name: str) -> dict[str, int]:
    if name not in PRESETS:
        raise ValueError(f"unknown preset: {name}")
    return save(dict(PRESETS[name]))


def apply_intervals(body: dict[str, int]) -> dict[str, int]:
    current = load()
    for ch in CHANNELS:
        if ch in body:
            current[ch] = _clamp_minutes(body[ch])
    return save(current)