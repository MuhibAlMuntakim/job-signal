"""
JobSignal — CLI entrypoint.

Provides three commands:

    python main.py ingest            — Run one ingestion pass immediately.
    python main.py ingest --schedule — Start the 24-hour scheduled ingestion.
    python main.py status            — Print DB stats and last ingestion info.
"""

import argparse
import sys
from datetime import datetime, timezone

from loguru import logger

# Configure loguru: suppress debug messages unless running with verbose flag.
logger.remove()
logger.add(sys.stderr, level="INFO", colorize=True, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")


def _cmd_ingest(args: argparse.Namespace) -> None:
    """Handle the `ingest` command.

    Runs a single ingestion pass or starts the scheduler, depending
    on whether `--schedule` was passed.

    Args:
        args: Parsed CLI arguments.
    """
    if args.schedule:
        print("Starting scheduled ingestion (Ctrl+C to stop)…\n")
        from jobsignal.ingestion.scheduler import start_scheduler
        start_scheduler()
    else:
        print("Running one-time ingestion…\n")
        from jobsignal.ingestion.orchestrator import run_ingestion
        run_ingestion()


def _cmd_status(_args: argparse.Namespace) -> None:
    """Handle the `status` command.

    Queries the database for:
    - Total job count
    - Breakdown by source API
    - Unprocessed record count
    - Last ingestion timestamp

    Args:
        _args: Parsed CLI arguments (unused).
    """
    from sqlalchemy import func

    from jobsignal.database.models import JobPost
    from jobsignal.database.session import check_connection, get_session

    print("\n-- JobSignal Status ------------------------------\n")

    if not check_connection():
        print("  [ERR] Database connection failed. Check DATABASE_URL in .env\n")
        sys.exit(1)

    with get_session() as session:
        total = session.query(func.count(JobPost.id)).scalar() or 0
        unprocessed = (
            session.query(func.count(JobPost.id))
            .filter(JobPost.is_processed.is_(False))
            .scalar()
            or 0
        )

        # Per-source breakdown.
        by_source = (
            session.query(JobPost.source_api, func.count(JobPost.id))
            .group_by(JobPost.source_api)
            .all()
        )

        # Last ingestion timestamp.
        latest = (
            session.query(func.max(JobPost.ingested_at)).scalar()
        )

    print(f"  Total jobs in database : {total:,}")
    print(f"  Awaiting processing    : {unprocessed:,}")
    print()

    if by_source:
        print("  Breakdown by source:")
        for source, count in sorted(by_source):
            print(f"    * {source:<12} {count:>6,} jobs")
        print()

    if latest:
        # Make timezone-aware if naive.
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        print(f"  Last ingested at       : {latest.isoformat(timespec='seconds')}")
    else:
        print("  Last ingested at       : never")

    print("\n------------------------------------------------\n")


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate command handler."""
    parser = argparse.ArgumentParser(
        prog="jobsignal",
        description="JobSignal — AI-powered job market intelligence pipeline.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── ingest ────────────────────────────────────────────────────────────
    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Fetch jobs from all configured APIs and save to the database.",
    )
    ingest_parser.add_argument(
        "--schedule",
        action="store_true",
        help="Run ingestion on a repeating schedule (default: every 24 hours).",
    )

    # ── status ────────────────────────────────────────────────────────────
    subparsers.add_parser(
        "status",
        help="Show total job counts and last ingestion timestamp.",
    )

    args = parser.parse_args()

    if args.command == "ingest":
        _cmd_ingest(args)
    elif args.command == "status":
        _cmd_status(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
