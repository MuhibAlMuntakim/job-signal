"""
JobSignal — Database helper utilities for the ingestion layer.

Centralises the duplicate-detection logic so every API client reuses
the same deduplication strategy without duplicating SQL queries.
"""

from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from jobsignal.database.models import JobPost
from jobsignal.ingestion.schemas import JobPostSchema


def is_duplicate(
    session: Session,
    job_title: str,
    company_name: str,
    posted_date: Optional[datetime],
) -> bool:
    """Return True if an equivalent job post already exists in the database.

    Duplicate detection is based on the triplet:
        (job_title, company_name, posted_date)

    If `posted_date` is None the check falls back to just
    (job_title, company_name) to avoid treating every undated post as unique.

    Args:
        session: An active SQLAlchemy session.
        job_title: The job title to check.
        company_name: The company name to check.
        posted_date: The original posting date, or None.

    Returns:
        True if a matching record already exists.
    """
    query = session.query(JobPost).filter(
        JobPost.job_title == job_title,
        JobPost.company_name == company_name,
    )
    if posted_date is not None:
        query = query.filter(JobPost.posted_date == posted_date)

    exists = session.query(query.exists()).scalar()
    return bool(exists)


def save_job_post(session: Session, schema: JobPostSchema) -> Optional[str]:
    """Persist a single `JobPostSchema` to the database.

    Performs duplicate detection before inserting. Returns the ID of the
    record (newly created or existing).

    Args:
        session: An active SQLAlchemy session.
        schema: A validated `JobPostSchema` instance from an API client.

    Returns:
        The UUID string of the job post record.
    """
    # Check for existing
    query = session.query(JobPost).filter(
        JobPost.job_title == schema.job_title,
        JobPost.company_name == schema.company_name,
    )
    if schema.posted_date is not None:
        query = query.filter(JobPost.posted_date == schema.posted_date)
    
    existing = query.first()
    if existing:
        logger.debug(f"[EXISTING] {schema.company_name!r}: {schema.job_title!r}")
        return str(existing.id)

    record = JobPost(
        job_title=schema.job_title,
        company_name=schema.company_name,
        sector=schema.sector,
        location=schema.location,
        is_remote=schema.is_remote,
        salary_min=schema.salary_min,
        salary_max=schema.salary_max,
        salary_currency=schema.salary_currency,
        experience_level=schema.experience_level,
        required_skills=schema.required_skills,
        benefits=schema.benefits,
        job_description_raw=schema.job_description_raw,
        source_api=schema.source_api,
        source_url=schema.source_url,
        posted_date=schema.posted_date,
        is_processed=False,
    )
    session.add(record)
    session.flush() # Ensure ID is generated
    logger.debug(f"[SAVE] {schema.source_api} — {schema.company_name!r}: {schema.job_title!r}")
    return str(record.id)
