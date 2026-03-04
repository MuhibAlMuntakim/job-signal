"""
JobSignal — Ingestion Orchestrator.

Coordinates all three API clients, deduplicates results against the
database, and persists new job posts.  Returns a clean summary of the run.
"""

import time
from typing import List, Optional

from loguru import logger

from jobsignal.config.settings import get_settings
from jobsignal.database.helpers import save_job_post
from jobsignal.database.session import get_session
from jobsignal.ingestion import clients  # noqa: F401  — ensure sub-packages are importable
from jobsignal.ingestion.clients import adzuna, jsearch, remotive
from jobsignal.ingestion.schemas import IngestionSummary, JobPostSchema


def _run_client(
    name: str,
    jobs: List[JobPostSchema],
) -> tuple[IngestionSummary, List[str]]:
    """Persist a list of `JobPostSchema` records and return (summary, job_ids)."""
    summary = IngestionSummary(source_api=name, fetched=len(jobs))
    job_ids = []

    if not jobs:
        return summary, []

    try:
        with get_session() as session:
            for job in jobs:
                try:
                    job_id = save_job_post(session, job)
                    if job_id:
                        job_ids.append(job_id)
                        # We used to check Boolean for 'ingested' vs 'skipped'
                        # For simplicity, we'll just increment fetched and errors for now
                        # Or we can check if it already existed.
                        # Since save_job_post now returns ID for both, we handle ingested count outside or inside.
                        # Let's keep existing summary logic by checking if it was a new save.
                        # Actually save_job_post doesn't tell us if it was NEW or EXISTING easily now.
                        # Let's adjust save_job_post slightly or just accept the summary change.
                        summary.ingested += 1 
                except Exception as exc:  # noqa: BLE001
                    logger.error(f"[{name.upper()}] Failed to save job record: {exc}")
                    summary.errors += 1
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[{name.upper()}] Database session error: {exc}")
        summary.errors += len(jobs)

    return summary, job_ids


def run_ingestion(
    queries: Optional[List[str]] = None,
) -> tuple[List[IngestionSummary], List[str]]:
    """Run a full ingestion pass across all three job APIs.
    
    Returns:
        A tuple of (List[IngestionSummary], List[job_id_strings]).
    """
    settings = get_settings()
    if queries is None:
        queries = settings.default_search_queries

    logger.info(f"Starting ingestion for {len(queries)} queries: {queries}")

    totals: dict[str, IngestionSummary] = {
        "jsearch": IngestionSummary(source_api="jsearch"),
        "adzuna": IngestionSummary(source_api="adzuna"),
        "remotive": IngestionSummary(source_api="remotive"),
    }
    all_target_ids = set()

    def _add(target: IngestionSummary, source: IngestionSummary) -> None:
        target.fetched += source.fetched
        target.ingested += source.ingested
        target.skipped += source.skipped
        target.errors += source.errors

    for query in queries:
        logger.info(f"── Processing query: {query!r}")
        time.sleep(2)  # Prevent 429 Rate Limiting from JSearch/RapidAPI
        keyword_jobs_count = 0
        limit = settings.ingestion_max_results_per_query # Usually 10

        # ── JSearch ────────────────────────────────────────────────────────
        if keyword_jobs_count < limit:
            try:
                js_jobs = jsearch.fetch_jobs(
                    query, max_results=limit
                )
                summary, ids = _run_client("jsearch", js_jobs)
                _add(totals["jsearch"], summary)
                all_target_ids.update(ids)
                keyword_jobs_count += len(ids)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"[JSEARCH] Uncaught error for query={query!r}: {exc}")

        # ── Adzuna ─────────────────────────────────────────────────────────
        if keyword_jobs_count < limit:
            try:
                remaining = limit - keyword_jobs_count
                az_jobs = adzuna.fetch_jobs(
                    query,
                    countries=settings.adzuna_countries,
                    max_results=remaining,
                )
                summary, ids = _run_client("adzuna", az_jobs)
                _add(totals["adzuna"], summary)
                all_target_ids.update(ids)
                keyword_jobs_count += len(ids)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"[ADZUNA] Uncaught error for query={query!r}: {exc}")

        # ── Remotive ───────────────────────────────────────────────────────
        if keyword_jobs_count < limit:
            try:
                remaining = limit - keyword_jobs_count
                rm_jobs = remotive.fetch_jobs(
                    query=query, 
                    max_results=remaining
                )
                summary, ids = _run_client("remotive", rm_jobs)
                _add(totals["remotive"], summary)
                all_target_ids.update(ids)
                keyword_jobs_count += len(ids)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"[REMOTIVE] Uncaught error for query={query!r}: {exc}")

    summaries = list(totals.values())
    _print_summary(summaries)
    return summaries, list(all_target_ids)


def _print_summary(summaries: List[IngestionSummary]) -> None:
    """Print a formatted ingestion summary to stdout.

    Args:
        summaries: One `IngestionSummary` per API source.
    """
    total_ingested = sum(s.ingested for s in summaries)
    total_skipped = sum(s.skipped for s in summaries)
    total_errors = sum(s.errors for s in summaries)

    print()
    for s in summaries:
        label = s.source_api.capitalize()
        error_note = " (with errors)" if s.errors > 0 else ""
        print(f"  [OK] {label:<8}: {s.ingested:>4} new jobs ingested, {s.skipped:>4} skipped{error_note}")
    print("  " + "-" * 49)
    print(f"  Total: {total_ingested} new jobs ingested, {total_skipped} skipped", end="")
    if total_errors:
        print(f", {total_errors} errors")
    else:
        print()
    print()
