# World Event Globe

A real-time, interactive 3D globe for tracking global conflicts, disasters, and geopolitical events. Built as a high-signal intelligence and news visualization tool.

## Features

- **Live Event Ingestion**
  - GDELT 2.0 (15-minute updates)
  - RSS feeds from major conflict and humanitarian sources (ReliefWeb, EuObserver, Al Jazeera, etc.)
  - Structured data with severity scoring, geolocation, and actor extraction

- **Interactive Three.js Globe**
  - Realistic day/night cycle with accurate solar positioning
  - Zoom-aware country and city labels (only major countries shown at wide zoom)
  - Severity-scaled event markers with professional multi-layer animations
  - Click any event for cleaned summary, casualties, actors, and direct link to source

- **Backend**
  - FastAPI + SQLite (FTS5 full-text search)
  - APScheduler for automated ingestion
  - Country profiles (World Bank data + regime type, nuclear status, risk indices)
  - City profiles with strategic value tagging

## Tech Stack

- **Frontend**: Three.js + OrbitControls, vanilla HTML/JS
- **Backend**: FastAPI, APScheduler, httpx, feedparser, spaCy
- **Database**: SQLite with FTS5
- **Data Sources**: GDELT 2.0, RSS feeds, World Bank API

## Running Locally

```bash
cd /home/mike/globe
./start-globe.sh
```

This starts:
- FastAPI backend on `http://localhost:8091`
- Static frontend on `http://localhost:8090`
- Opens the globe in your default browser

## Project Structure

```
globe/
├── index.html              # Main Three.js globe frontend
├── start-globe.sh          # Launcher script
├── backend/
│   ├── server.py           # FastAPI app
│   ├── db.py               # SQLite layer + FTS5
│   └── ingestion/
│       ├── gdelt.py
│       ├── rss.py
│       ├── enrich.py
│       ├── scheduler.py
│       ├── countries.py
│       └── cities.py
├── data/
│   └── globe.db
└── README.md
```

## Roadmap

- [ ] ACLED integration (high-quality structured conflict data)
- [ ] Wikidata entity enrichment (leaders, alliances, sanctions)
- [ ] Event detail deep links + source credibility scoring
- [ ] Export / share current view
- [ ] Mobile-responsive UI

## Notes

This project is designed as a personal intelligence tool. All data is pulled from public sources. No API keys are stored in the repository.

---

Built with first-principles focus on clarity, signal, and real-world usefulness.
