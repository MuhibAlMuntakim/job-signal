"""
JobSignal — Remotive API client.

Fetches remote-only job postings from Remotive's free, open API.
No API key required.

API docs: https://remotive.com/api/remote-jobs
Endpoint: https://remotive.com/api/remote-jobs?category={category}
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from jobsignal.ingestion.schemas import ExperienceLevel, JobPostSchema

_SOURCE = "remotive"
_BASE_URL = "https://remotive.com/api/remote-jobs"

# Categories relevant to data and AI roles on Remotive.
_CATEGORIES = ["software-dev", "data"]


def _infer_experience_level(text: str) -> str:
    """Infer experience level from job title or description text.

    Args:
        text: Combined job title + description.

    Returns:
        A valid ExperienceLevel string.
    """
    lower = text.lower()
    if any(kw in lower for kw in ("lead", "principal", "staff", "director", "head of")):
        return ExperienceLevel.LEAD
    if any(kw in lower for kw in ("senior", "sr.", "sr ")):
        return ExperienceLevel.SENIOR
    if any(kw in lower for kw in ("junior", "jr.", "jr ", "entry", "graduate", "intern")):
        return ExperienceLevel.JUNIOR
    if any(kw in lower for kw in ("mid", "mid-level", "intermediate")):
        return ExperienceLevel.MID
    return ExperienceLevel.UNKNOWN


def _parse_posted_date(job: Dict[str, Any]) -> Optional[datetime]:
    """Parse the publication date from a Remotive job record.

    Remotive provides `publication_date` in ISO 8601 format.

    Args:
        job: Raw job dict from the Remotive API.

    Returns:
        A timezone-aware `datetime` or None.
    """
    raw = job.get("publication_date")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return None


def _normalise(job: Dict[str, Any]) -> Optional[JobPostSchema]:
    """Convert a single Remotive API record into a `JobPostSchema`.

    Returns None if the record is missing required fields.

    Args:
        job: Raw job dict from the Remotive API response.

    Returns:
        A `JobPostSchema` instance, or None.
    """
    job_title = (job.get("title") or "").strip()
    company_name = (job.get("company_name") or "").strip()
    description = (job.get("description") or "").strip()

    if not job_title or not company_name or not description:
        logger.debug(f"[REMOTIVE] Skipping record with missing required fields: {job.get('id')}")
        return None

    # Remotive provides a plain-text salary string (not always structured).
    salary_raw = (job.get("salary") or "").strip() or None
    # We store it in the benefits field since it's unstructured text.
    benefits_text = f"Salary: {salary_raw}" if salary_raw else None

    # Remotive jobs are all remote by definition.
    is_remote = True

    location = (job.get("candidate_required_location") or "Remote").strip()
    sector = (job.get("category") or None)
    tags = job.get("tags") or []
    skills_text = ", ".join(tags) if tags else None

    try:
        return JobPostSchema(
            job_title=job_title,
            company_name=company_name,
            sector=sector,
            location=location,
            is_remote=is_remote,
            salary_min=None,
            salary_max=None,
            salary_currency=None,
            experience_level=_infer_experience_level(f"{job_title} {description}"),
            required_skills=skills_text,
            benefits=benefits_text,
            job_description_raw=description,
            source_api=_SOURCE,
            source_url=job.get("url") or None,
            posted_date=_parse_posted_date(job),
        )
    except Exception as exc:
        logger.error(f"[{_SOURCE.upper()}] Normalisation error: {exc}")
        return None


@retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _fetch_category(client: httpx.Client, category: str) -> List[Dict[str, Any]]:
    """Fetch all jobs in a given Remotive category.

    Remotive returns all results for a category in a single response
    (no pagination needed).

    Args:
        client: Shared httpx.Client.
        category: Category slug, e.g. "software-dev" or "data".

    Returns:
        A list of raw job dicts.
    """
    logger.debug(f"[REMOTIVE] Fetching category={category!r}")
    response = client.get(
        _BASE_URL,
        params={"category": category},
        timeout=30.0,
    )
    if response.status_code == 429:
        logger.warning(f"[REMOTIVE] Rate limited for category={category!r}. Backing off…")
    response.raise_for_status()
    return response.json().get("jobs", [])


def fetch_jobs(query: Optional[str] = None, max_results: int = 10) -> List[JobPostSchema]:
    """Fetch jobs from Remotive across relevant categories.
    
    Args:
        query: Optional keyword to filter by job title (case-insensitive).
        max_results: Maximum number of jobs to return.
    """
    jobs: List[JobPostSchema] = []
    seen_ids: set = set()

    with httpx.Client() as client:
        for category in _CATEGORIES:
            try:
                raw_jobs = _fetch_category(client, category)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                logger.error(f"[REMOTIVE] Failed to fetch category={category!r}: {exc}")
                continue

            for raw in raw_jobs:
                job_id = raw.get("id")
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                # Optional title-based query filter.
                if query:
                    title = (raw.get("title") or "").lower()
                    if query.lower() not in title:
                        continue

                schema = _normalise(raw)
                if schema:
                    jobs.append(schema)

    logger.info(f"[REMOTIVE] Fetched {len(jobs)} jobs (query={query!r}), limiting to {max_results}")
    return jobs[:max_results]
