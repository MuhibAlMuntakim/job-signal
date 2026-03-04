"""
JobSignal — Ingestion Scheduler.

Uses APScheduler to run the full ingestion orchestrator on a repeating
schedule (default: every 24 hours).  The first run is triggered
immediately on startup.

Usage:
    python -m jobsignal.ingestion.scheduler
    # or via the CLI:
    python main.py ingest --schedule
"""

from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger

from jobsignal.config.settings import get_settings
from jobsignal.ingestion.orchestrator import run_ingestion


def _ingestion_job() -> None:
    """Scheduled callback: run a full ingestion pass and log the result.

    This function is called by APScheduler on each trigger.  Any
    uncaught exception is caught and logged so the scheduler stays alive.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    logger.info(f"Scheduled ingestion starting at {now}")
    try:
        summaries = run_ingestion()
        total = sum(s.ingested for s in summaries)
        logger.info(f"Scheduled ingestion complete. {total} new jobs ingested.")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Scheduled ingestion failed: {exc}")


def start_scheduler() -> None:
    """Start the blocking APScheduler and run ingestion on a fixed interval.

    - Fires immediately on startup (using `next_run_time=datetime.now()`).
    - Repeats every `settings.schedule_interval_hours` hours.
    - Blocks the calling thread (intended to run in main process or
      as a dedicated subprocess).

    Press Ctrl+C to stop.
    """
    settings = get_settings()
    interval_hours = settings.schedule_interval_hours

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        _ingestion_job,
        trigger="interval",
        hours=interval_hours,
        next_run_time=datetime.now(timezone.utc),  # Fire immediately on start.
        id="ingestion_job",
        name="JobSignal Ingestion",
        misfire_grace_time=600,  # Allow up to 10-minute delay before skipping a run.
    )

    logger.info(
        f"Scheduler started. Ingestion will run every {interval_hours} hour(s). "
        "Press Ctrl+C to stop."
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by user.")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    start_scheduler()
