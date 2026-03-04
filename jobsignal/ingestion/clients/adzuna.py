"""
JobSignal — Adzuna API client.

Fetches job postings by search query and country, normalises them
into `JobPostSchema` instances.

API docs: https://developer.adzuna.com/docs/search
Endpoint: https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
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

from jobsignal.config.settings import get_settings
from jobsignal.ingestion.schemas import ExperienceLevel, JobPostSchema

_SOURCE = "adzuna"
_BASE_URL = "https://api.adzuna.com/v1/api/jobs"
_PAGE_SIZE = 50  # Adzuna's maximum results_per_page.


def _infer_experience_level(text: str) -> str:
    """Infer experience level from job title or description text.

    Args:
        text: Combined job title + description string.

    Returns:
        A valid ExperienceLevel string value.
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
    """Parse the creation timestamp from an Adzuna job record.

    Args:
        job: Raw job dict from the Adzuna API.

    Returns:
        A timezone-aware `datetime` or None.
    """
    raw = job.get("created")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return None


def _normalise(job: Dict[str, Any], country: str) -> Optional[JobPostSchema]:
    """Convert a single Adzuna result dict into a `JobPostSchema`.

    Returns None if the record is missing required fields.

    Args:
        job: Raw job dict from the Adzuna API.
        country: The country code this result came from (e.g. "us").

    Returns:
        A `JobPostSchema` instance, or None.
    """
    job_title = (job.get("title") or "").strip()
    company_name = (
        (job.get("company") or {}).get("display_name") or ""
    ).strip()
    description = (job.get("description") or "").strip()

    if not job_title or not company_name or not description:
        logger.debug(f"[ADZUNA] Skipping record with missing required fields: {job.get('id')}")
        return None

    # Adzuna provides salary range directly.
    salary_min = job.get("salary_min")
    salary_max = job.get("salary_max")
    currency = "GBP" if country == "gb" else "USD"  # Adzuna doesn't return currency codes.

    location_parts = filter(None, [
        (job.get("location") or {}).get("display_name"),
    ])
    location = ", ".join(location_parts) or None

    # Adzuna category → sector
    category = (job.get("category") or {}).get("label") or None

    # Remote detection from Adzuna contract_type or title
    is_remote = "remote" in job_title.lower() or "remote" in description.lower()

    posted_date = _parse_posted_date(job)

    try:
        return JobPostSchema(
            job_title=job_title,
            company_name=company_name,
            sector=category,
            location=location,
            is_remote=is_remote,
            salary_min=int(salary_min) if salary_min else None,
            salary_max=int(salary_max) if salary_max else None,
            salary_currency=currency,
            experience_level=_infer_experience_level(f"{job_title} {description}"),
            required_skills=None,
            benefits=None,
            job_description_raw=description,
            source_api=_SOURCE,
            source_url=job.get("redirect_url") or None,
            posted_date=posted_date,
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
def _fetch_page(
    client: httpx.Client,
    query: str,
    country: str,
    page: int,
    app_id: str,
    app_key: str,
) -> List[Dict[str, Any]]:
    """Fetch a single page of Adzuna results.

    Decorated with tenacity for exponential backoff on rate limits (429)
    and transient network errors.

    Args:
        client: Shared httpx.Client.
        query: Search query string.
        country: Two-letter country code (e.g. "us").
        page: 1-indexed page number.
        app_id: Adzuna application ID.
        app_key: Adzuna application key.

    Returns:
        A list of raw job dicts.
    """
    url = f"{_BASE_URL}/{country}/search/{page}"
    logger.debug(f"[ADZUNA] Fetching page {page} for query={query!r}, country={country!r}")
    response = client.get(
        url,
        params={
            "app_id": app_id,
            "app_key": app_key,
            "what": query,
            "results_per_page": _PAGE_SIZE,
            "content-type": "application/json",
        },
        timeout=30.0,
    )
    if response.status_code == 429:
        logger.warning(f"[ADZUNA] Rate limited on page {page}. Backing off…")
    response.raise_for_status()
    return response.json().get("results", [])


def fetch_jobs(
    query: str,
    countries: Optional[List[str]] = None,
    max_results: int = 100,
) -> List[JobPostSchema]:
    """Fetch jobs from Adzuna for a given query across one or more countries.

    Paginates through each country's results up to `max_results` total.
    If either API credential is missing, returns an empty list.

    Args:
        query: Job search query, e.g. "Machine Learning Engineer".
        countries: List of two-letter country codes. Defaults to ["us", "gb"].
        max_results: Maximum total results to fetch across all countries.

    Returns:
        A list of normalised `JobPostSchema` instances.
    """
    settings = get_settings()
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        logger.warning("[ADZUNA] ADZUNA_APP_ID or ADZUNA_APP_KEY is not set — skipping Adzuna.")
        return []

    if countries is None:
        countries = settings.adzuna_countries

    jobs: List[JobPostSchema] = []
    per_country_limit = max(1, max_results // len(countries))
    max_pages = max(1, per_country_limit // _PAGE_SIZE)

    with httpx.Client() as client:
        for country in countries:
            for page in range(1, max_pages + 1):
                try:
                    raw_jobs = _fetch_page(
                        client, query, country, page,
                        settings.adzuna_app_id, settings.adzuna_app_key,
                    )
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    logger.error(
                        f"[ADZUNA] Failed to fetch page {page} "
                        f"for {query!r} / {country!r}: {exc}"
                    )
                    break

                if not raw_jobs:
                    logger.debug(f"[ADZUNA] No more results on page {page} for {country!r}.")
                    break

                for raw in raw_jobs:
                    schema = _normalise(raw, country)
                    if schema:
                        jobs.append(schema)

                if len(raw_jobs) < _PAGE_SIZE:
                    break

    logger.info(f"[ADZUNA] Fetched {len(jobs)} jobs for query={query!r}, limiting to {max_results}")
    return jobs[:max_results]
