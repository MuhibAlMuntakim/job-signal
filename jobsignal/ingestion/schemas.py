"""
JobSignal — Ingestion Pydantic schemas.

Defines the `JobPostSchema` — the unified contract that every API client
must return.  This schema is source-agnostic and maps cleanly onto the
`JobPost` SQLAlchemy model.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class ExperienceLevel(str, Enum):
    """Allowed values for the experience_level field."""

    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    UNKNOWN = "unknown"


class JobPostSchema(BaseModel):
    """Unified Pydantic schema for a single job posting.

    All three API clients (JSearch, Adzuna, Remotive) must normalise
    their raw API responses into this schema.  The orchestrator then
    persists instances to the database via the SQLAlchemy `JobPost` model.
    """

    # ── Core fields ────────────────────────────────────────────────────────
    job_title: str = Field(..., description="Exact job title as advertised.")
    company_name: str = Field(..., description="Hiring company name.")
    sector: Optional[str] = Field(None, description="Industry or sector if available.")
    location: Optional[str] = Field(None, description="City, region, or 'Remote'.")
    is_remote: bool = Field(False, description="True if the role allows full remote work.")

    # ── Compensation ───────────────────────────────────────────────────────
    salary_min: Optional[int] = Field(None, description="Minimum advertised salary (integer).")
    salary_max: Optional[int] = Field(None, description="Maximum advertised salary (integer).")
    salary_currency: Optional[str] = Field(None, description="Currency code, e.g. USD, GBP.")

    # ── Classification ─────────────────────────────────────────────────────
    experience_level: ExperienceLevel = Field(
        ExperienceLevel.UNKNOWN, description="Inferred experience level."
    )

    # ── Raw text ───────────────────────────────────────────────────────────
    required_skills: Optional[str] = Field(
        None, description="Raw text describing required skills."
    )
    benefits: Optional[str] = Field(None, description="Raw text describing benefits.")
    job_description_raw: str = Field(..., description="Full original job description text.")

    # ── Source metadata ────────────────────────────────────────────────────
    source_api: str = Field(
        ..., description="API identifier: 'jsearch' | 'adzuna' | 'remotive'."
    )
    source_url: Optional[str] = Field(None, description="Direct link to the original post.")
    posted_date: Optional[datetime] = Field(
        None, description="Date the job was originally posted."
    )

    @field_validator("job_title", "company_name", mode="before")
    @classmethod
    def strip_whitespace(cls, value: str) -> str:
        """Strip leading/trailing whitespace from string fields."""
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("experience_level", mode="before")
    @classmethod
    def coerce_experience_level(cls, value: Optional[str]) -> str:
        """Normalise any unknown experience level string to 'unknown'."""
        if value is None:
            return ExperienceLevel.UNKNOWN
        normalised = str(value).lower().strip()
        valid = {e.value for e in ExperienceLevel}
        return normalised if normalised in valid else ExperienceLevel.UNKNOWN

    model_config = {"use_enum_values": True}


class IngestionSummary(BaseModel):
    """Summary result returned by each API client after an ingestion run."""

    source_api: str
    fetched: int = Field(0, description="Total records fetched from the API.")
    ingested: int = Field(0, description="New records saved to the database.")
    skipped: int = Field(0, description="Records skipped because they were duplicates.")
    errors: int = Field(0, description="Records that failed to parse or save.")
