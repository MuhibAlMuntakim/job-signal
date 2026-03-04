"""
JobSignal — SQLAlchemy ORM models.

Defines the `job_posts` table that is the central store for all
raw job data ingested from external APIs.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all SQLAlchemy models."""

    pass


class JobPost(Base):
    """Represents a single job posting as stored in the database.

    This is the canonical record for all raw job data. The `is_processed`
    flag is the primary handoff mechanism to Module 2: once set to True,
    the processing pipeline knows the record has been enriched.
    """

    __tablename__ = "job_posts"

    # ── Primary Key ────────────────────────────────────────────────────────
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Auto-generated UUID primary key.",
    )

    # ── Core job info ──────────────────────────────────────────────────────
    job_title = Column(Text, nullable=False, comment="Job title as posted.")
    company_name = Column(Text, nullable=False, comment="Hiring company name.")
    sector = Column(Text, nullable=True, comment="Industry or sector, if available.")
    location = Column(Text, nullable=True, comment="City, region, or 'Remote'.")
    is_remote = Column(
        Boolean, nullable=False, default=False, comment="True if the role is fully remote."
    )

    # ── Compensation ───────────────────────────────────────────────────────
    salary_min = Column(Integer, nullable=True, comment="Minimum advertised salary (integer).")
    salary_max = Column(Integer, nullable=True, comment="Maximum advertised salary (integer).")
    salary_currency = Column(Text, nullable=True, comment="Currency code, e.g. USD, GBP.")

    # ── Classification ─────────────────────────────────────────────────────
    experience_level = Column(
        Text,
        nullable=True,
        comment="One of: junior / mid / senior / lead / unknown.",
    )

    # ── Raw text fields ────────────────────────────────────────────────────
    required_skills = Column(
        Text, nullable=True, comment="Raw skills section text from the job description."
    )
    benefits = Column(
        Text, nullable=True, comment="Raw benefits section text from the job description."
    )
    job_description_raw = Column(
        Text, nullable=False, comment="Full original job description text."
    )

    # ── Source metadata ────────────────────────────────────────────────────
    source_api = Column(
        Text, nullable=False, comment="Which API delivered this record: jsearch | adzuna | remotive."
    )
    source_url = Column(Text, nullable=True, comment="Direct link to the original job post.")
    posted_date = Column(
        DateTime(timezone=True), nullable=True, comment="Date the job was originally posted."
    )

    # ── Pipeline control ───────────────────────────────────────────────────
    ingested_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="UTC timestamp of when this record was written to the database.",
    )
    is_processed = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="Flag for Module 2: False = awaiting processing.",
    )
    is_scored = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="True if the job has been scored against the active candidate profile.",
    )

    def __repr__(self) -> str:
        """Return a concise string representation for debugging."""
        return (
            f"<JobPost id={self.id!s:.8} "
            f"title={self.job_title!r} "
            f"company={self.company_name!r} "
            f"source={self.source_api!r}>"
        )


class CandidateProfile(Base):
    """Represents a candidate's structured profile extracted from their resume."""

    __tablename__ = "candidate_profiles"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    full_name = Column(Text, nullable=False)
    email = Column(Text, nullable=True)
    extracted_skills = Column(JSONB, nullable=False, comment="List of technical skill strings.")
    experience_years = Column(Integer, nullable=True)
    experience_level = Column(
        Text,
        nullable=False,
        comment="junior / mid / senior / lead",
    )
    sectors_of_experience = Column(JSONB, nullable=False)
    preferred_remote = Column(
        Text,
        nullable=False,
        default="any",
        comment="remote / onsite / hybrid / any",
    )
    preferred_salary_min = Column(Integer, nullable=True)
    preferred_salary_currency = Column(Text, default="USD")
    preferred_sectors = Column(JSONB, nullable=True)
    resume_raw_text = Column(Text, nullable=False)
    resume_file_name = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    is_active = Column(Boolean, default=True)

    def __repr__(self) -> str:
        return f"<CandidateProfile name={self.full_name!r} active={self.is_active}>"


class JobScore(Base):
    """Represents the match score of a job post against a candidate profile."""

    __tablename__ = "job_scores"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    job_post_id = Column(
        UUID(as_uuid=True),
        ForeignKey("job_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    score_total = Column(Float, nullable=False)  # 0 to 100
    score_skill_match = Column(Float, nullable=False)  # 0 to 40
    score_remote_match = Column(Float, nullable=False)  # 0 to 20
    score_salary_match = Column(Float, nullable=False)  # 0 to 20
    score_sector_match = Column(Float, nullable=False)  # 0 to 20
    score_breakdown = Column(JSONB, nullable=False)
    scored_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<JobScore total={self.score_total}>"
