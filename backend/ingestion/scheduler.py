"""
Scheduler for automated ingestion runs.
GDELT: every 15 minutes
RSS: every 30 minutes
Enrichment: continuous (process new raw items)
"""
import time
import signal
import sys
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from backend.ingestion.gdelt import GDELTIngester
from backend.ingestion.rss import RSSEnginer
from backend.ingestion.enrich import Enricher
from backend.db import get_conn, query

class IngestionScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.gdelt = GDELTIngester()
        self.rss = RSSEnginer()
        self.enricher = Enricher()
        self.running = False

        # Graceful shutdown
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        print(f"\n[Scheduler] Signal {signum} received, shutting down...")
        self.stop()

    def run_gdelt(self):
        """GDELT ingestion job."""
        print(f"[Scheduler] {datetime.utcnow().isoformat()} - GDELT run")
        try:
            count = self.gdelt.run_once()
            if count > 0:
                self.run_enrichment(limit=count * 2)  # Process new items
        except Exception as e:
            print(f"[Scheduler] GDELT job failed: {e}")

    def run_rss(self):
        """RSS ingestion job."""
        print(f"[Scheduler] {datetime.utcnow().isoformat()} - RSS run")
        try:
            count = self.rss.run_all()
            if count > 0:
                self.run_enrichment(limit=count * 2)
        except Exception as e:
            print(f"[Scheduler] RSS job failed: {e}")

    def run_enrichment(self, limit: int = 100):
        """Process unenriched raw items into events."""
        print(f"[Scheduler] {datetime.utcnow().isoformat()} - Enrichment run (limit={limit})")
        # Get raw items that haven't been enriched
        rows = query("""
            SELECT ri.* FROM raw_items ri
            LEFT JOIN events e ON e.raw_item_id = ri.id
            WHERE e.id IS NULL
            ORDER BY ri.fetched_at DESC
            LIMIT ?
        """, (limit,))

        enriched = 0
        errors = 0
        for row in rows:
            raw_item = dict(row)
            try:
                event = self.enricher.enrich(raw_item)
                if event:
                    self.enricher.store_event(event)
                    enriched += 1
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f"[Scheduler] Enrichment error on item {raw_item.get('id', '?')}: {e}")

        status = f"Enriched {enriched} new events"
        if errors:
            status += f" ({errors} errors)"
        print(f"[Scheduler] {status}")

    def run_maintenance(self):
        """Daily maintenance: cleanup, stats, re-enrich low-confidence."""
        print(f"[Scheduler] {datetime.utcnow().isoformat()} - Maintenance run")
        try:
            with get_conn() as conn:
                # Update source stats
                conn.execute("""
                    UPDATE sources SET
                    total_items = (SELECT COUNT(*) FROM raw_items WHERE source_id = sources.id),
                    total_events = (SELECT COUNT(*) FROM events e
                                    JOIN raw_items ri ON e.raw_item_id = ri.id
                                    WHERE ri.source_id = sources.id)
                """)

                # Delete old raw items (> 30 days) that have been enriched
                conn.execute("""
                    DELETE FROM raw_items
                    WHERE fetched_at < datetime('now', '-30 days')
                    AND id IN (SELECT raw_item_id FROM events)
                """)

                # Re-enrich low-confidence events from last 7 days
                conn.execute("""
                    UPDATE events SET confidence = 0
                    WHERE confidence < 0.4
                    AND published_at > datetime('now', '-7 days')
                """)

                conn.commit()

            print("[Scheduler] Maintenance complete")
        except Exception as e:
            print(f"[Scheduler] Maintenance failed: {e}")

    def start(self):
        """Start the scheduler."""
        if self.running:
            return

        # GDELT every 15 minutes
        self.scheduler.add_job(
            self.run_gdelt,
            IntervalTrigger(minutes=15),
            id="gdelt",
            name="GDELT 2.0 Events Ingestion",
            max_instances=1,
            coalesce=True
        )

        # RSS every 30 minutes
        self.scheduler.add_job(
            self.run_rss,
            IntervalTrigger(minutes=30),
            id="rss",
            name="RSS Feed Ingestion",
            max_instances=1,
            coalesce=True
        )

        # Enrichment every 5 minutes (process backlog)
        self.scheduler.add_job(
            self.run_enrichment,
            IntervalTrigger(minutes=5),
            id="enrich",
            name="Event Enrichment",
            max_instances=1,
            coalesce=True
        )

        # Daily maintenance at 03:00 UTC
        self.scheduler.add_job(
            self.run_maintenance,
            trigger="cron",
            hour=3, minute=0,
            id="maintenance",
            name="Daily Maintenance",
            max_instances=1
        )

        self.scheduler.start()
        self.running = True
        print("[Scheduler] Started - GDELT: 15min, RSS: 30min, Enrich: 5min, Maintenance: daily 03:00 UTC")

        # Run once immediately on start
        self.run_gdelt()
        self.run_rss()
        self.run_enrichment(limit=200)

    def stop(self):
        """Stop the scheduler."""
        if self.running:
            self.scheduler.shutdown(wait=True)
            self.running = False
            print("[Scheduler] Stopped")

    def run_forever(self):
        """Block until shutdown."""
        self.start()
        try:
            while self.running:
                time.sleep(10)
        except KeyboardInterrupt:
            self.stop()


def main():
    scheduler = IngestionScheduler()
    scheduler.run_forever()


if __name__ == "__main__":
    main()