"""
JobSignal — JSearch API client (via RapidAPI).

Fetches job postings by search query and normalises them into
`JobPostSchema` instances.

API docs: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
Endpoint: https://jsearch.p.rapidapi.com/search
"""

import re
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

from jobsignal.config.settings import get_settings
from jobsignal.ingestion.schemas import ExperienceLevel, JobPostSchema

_SOURCE = "jsearch"
_BASE_URL = "https://jsearch.p.rapidapi.com/search"
_PAGE_SIZE = 10  # JSearch returns up to 10 results per page.


def _infer_experience_level(text: str) -> str:
    """Infer experience level from a job description string.

    Scans for common keywords and returns the closest matching
    `ExperienceLevel` value.

    Args:
        text: Any free-text string (usually the job title or description).

    Returns:
        A valid ExperienceLevel string value.
    """
    lower = text.lower()
    if any(kw in lower for kw in ("lead", "principal", "staff", "director")):
        return ExperienceLevel.LEAD
    if any(kw in lower for kw in ("senior", "sr.", "sr ")):
        return ExperienceLevel.SENIOR
    if any(kw in lower for kw in ("junior", "jr.", "jr ", "entry", "graduate", "intern")):
        return ExperienceLevel.JUNIOR
    if any(kw in lower for kw in ("mid", "mid-level", "intermediate")):
        return ExperienceLevel.MID
    return ExperienceLevel.UNKNOWN


def _parse_salary(job: Dict[str, Any]) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """Extract min salary, max salary, and currency from a JSearch job record.

    Returns:
        A tuple of (salary_min, salary_max, salary_currency).
    """
    min_sal = job.get("job_min_salary")
    max_sal = job.get("job_max_salary")
    currency = job.get("job_salary_currency")

    salary_period = (job.get("job_salary_period") or "").lower()

    # Annualise monthly or hourly figures for consistency.
    if min_sal and salary_period == "monthly":
        min_sal = int(min_sal * 12)
    if max_sal and salary_period == "monthly":
        max_sal = int(max_sal * 12)
    if min_sal and salary_period == "hourly":
        min_sal = int(min_sal * 2080)  # 52 weeks × 40 hours
    if max_sal and salary_period == "hourly":
        max_sal = int(max_sal * 2080)

    return (
        int(min_sal) if min_sal else None,
        int(max_sal) if max_sal else None,
        currency or None,
    )


def _parse_posted_date(job: Dict[str, Any]) -> Optional[datetime]:
    """Parse the posted timestamp from a JSearch job record.

    Args:
        job: Raw job dict from the JSearch API response.

    Returns:
        A timezone-aware `datetime` or None if parsing fails.
    """
    ts = job.get("job_posted_at_timestamp")
    if ts:
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc)
        except (ValueError, OSError):
            pass
    raw = job.get("job_posted_at_datetime_utc")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return None


def _normalise(job: Dict[str, Any]) -> Optional[JobPostSchema]:
    """Convert a single JSearch API result dict into a `JobPostSchema`.

    Returns None if the record is missing required fields.

    Args:
        job: Raw job dict from the API.

    Returns:
        A `JobPostSchema` instance, or None.
    """
    job_title = (job.get("job_title") or "").strip()
    company_name = (job.get("employer_name") or "").strip()
    description = (job.get("job_description") or "").strip()

    if not job_title or not company_name or not description:
        logger.debug(f"[JSEARCH] Skipping record with missing required fields: {job.get('job_id')}")
        return None

    salary_min, salary_max, salary_currency = _parse_salary(job)
    posted_date = _parse_posted_date(job)

    location_parts = filter(None, [
        job.get("job_city"),
        job.get("job_state"),
        job.get("job_country"),
    ])
    location = ", ".join(location_parts) or None

    try:
        return JobPostSchema(
            job_title=job_title,
            company_name=company_name,
            sector=job.get("job_publisher") or None,
            location=location,
            is_remote=bool(job.get("job_is_remote", False)),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            experience_level=_infer_experience_level(f"{job_title} {description}"),
            required_skills=job.get("job_required_skills") or None,
            benefits=None,
            job_description_raw=description,
            source_api=_SOURCE,
            source_url=job.get("job_apply_link") or None,
            posted_date=posted_date,
        )
    except Exception as exc:
        logger.error(f"[{_SOURCE.upper()}] Normalisation error: {exc}")
        return None


@retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)),
    wait=wait_exponential(multiplier=2, min=5, max=120),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _fetch_page(
    client: httpx.Client, query: str, page: int, rapidapi_key: str
) -> List[Dict[str, Any]]:
    """Fetch a single page of results from JSearch.

    Decorated with tenacity for exponential backoff on transient errors
    and rate-limit (429) responses.

    Args:
        client: A shared `httpx.Client` instance.
        query: The search query string.
        page: 1-indexed page number.
        rapidapi_key: The RapidAPI authentication key.

    Returns:
        A list of raw job dicts from the API data array.

    Raises:
        httpx.HTTPStatusError: On non-2xx responses after all retries.
    """
    logger.debug(f"[JSEARCH] Fetching page {page} for query={query!r}")
    response = client.get(
        _BASE_URL,
        params={"query": query, "page": str(page), "num_pages": "1"},
        headers={
            "X-RapidAPI-Key": rapidapi_key,
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
        },
        timeout=30.0,
    )
    if response.status_code == 429:
        logger.warning(f"[JSEARCH] Rate limited on page {page}. Backing off…")
    response.raise_for_status()
    return response.json().get("data", [])


def fetch_jobs(query: str, max_results: int = 100) -> List[JobPostSchema]:
    """Fetch jobs from JSearch for a given search query.

    Paginates through results up to `max_results` total.  Skips any
    records that fail normalisation.  If the API key is not configured,
    returns an empty list immediately.

    Args:
        query: The job search query, e.g. "AI Engineer".
        max_results: Upper bound on total results to fetch.

    Returns:
        A list of normalised `JobPostSchema` instances.
    """
    settings = get_settings()
    if not settings.rapidapi_key:
        logger.warning("[JSEARCH] RAPIDAPI_KEY is not set — skipping JSearch.")
        return []

    jobs: List[JobPostSchema] = []
    max_pages = max_results // _PAGE_SIZE

    with httpx.Client() as client:
        for page in range(1, max_pages + 1):
            try:
                raw_jobs = _fetch_page(client, query, page, settings.rapidapi_key)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                logger.error(f"[JSEARCH] Failed to fetch page {page} for {query!r}: {exc}")
                break

            if not raw_jobs:
                logger.debug(f"[JSEARCH] No more results on page {page}.")
                break

            for raw in raw_jobs:
                schema = _normalise(raw)
                if schema:
                    jobs.append(schema)

            if len(raw_jobs) < _PAGE_SIZE:
                break  # Last page reached before hitting the limit.

    logger.info(f"[JSEARCH] Fetched {len(jobs)} jobs for query={query!r}")
    return jobs
