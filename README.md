# GLOBE // Live Event Monitor

A self-contained, real-time 3D globe for tracking conflicts, unrest, disasters,
and geopolitical events. One Python process, one port, zero external CDNs.

![style](https://img.shields.io/badge/aesthetic-ops%20console-orange)

## Design

Deliberately **not** the usual glowing blue-marble look. The basemap is drawn
procedurally at runtime from Natural Earth vector data (bundled TopoJSON) —
latitude-banded biome land (ice → boreal → temperate → desert → tropics), crisp
coastlines and country borders, a real day/night terminator, monospace ops-console
UI, and a single amber→red severity palette.

## Data sources (all public, no API keys)

| Channel | Source                         | Cadence | Notes                                    |
|---------|--------------------------------|---------|------------------------------------------|
| gdelt   | GDELT 2.0 events export        | 15 min  | CAMEO-coded conflict/unrest/diplomacy     |
| usgs    | USGS earthquakes (M4.5+, week) | 15 min  | Exact coordinates + magnitude severity    |
| gdacs   | GDACS disaster alerts          | 20 min  | Green/Orange/Red alert severity           |
| rss     | BBC, Al Jazeera, UN, ReliefWeb, DW, France 24 | 10 min | Geolocated via built-in gazetteer |

Events are deduplicated by id and source URL, severity-scored 0–1, stored in
SQLite with FTS5 full-text search, and pruned after 14 days.

**Update cadence:** RSS every 10 min, GDELT/USGS every 15 min, GDACS every 20 min.
The UI re-fetches the local database every 60 s. Click **↻ Refresh** (or press `r`)
to pull all feeds immediately when something is breaking fast.

## Run

```bash
./start.sh            # creates .venv on first run, then serves http://localhost:8090
```

The UI shows clearly-labeled **sample data** until the first ingest completes
(usually < 1 minute), then switches to LIVE automatically.

## Layout

```
index.html               UI shell
static/
  app.js                 data layer, feed, filters, detail panel
  globe.js               Three.js renderer (procedural basemap, markers, terminator)
  styles.css             ops-console theme
  vendor/                three.js, OrbitControls, topojson-client (vendored, offline-safe)
data/
  countries-50m.json     Natural Earth boundaries (render)
  countries-110m.json    Natural Earth boundaries (gazetteer centroids)
  sample-events.json     fallback dataset (fictional, labeled)
backend/
  server.py              FastAPI app + static serving + scheduler
  ingest.py              GDELT / USGS / GDACS / RSS ingestion
  geo.py                 gazetteer (country centroids derived from TopoJSON + city list)
  db.py                  SQLite + FTS5
```

## API

- `GET /api/events?since_hours=72&category=conflict,hazard&min_severity=0.45&q=sudan&limit=1500`
- `GET /api/events/{id}`
- `GET /api/stats` — counts, per-channel ingest log
- `POST /api/refresh` — force immediate ingest from all feeds
- `GET /api/health`

## Env

- `PORT` — listen port (default 8090)
- `GLOBE_NO_INGEST=1` — serve UI/API without background ingestion (dev)
