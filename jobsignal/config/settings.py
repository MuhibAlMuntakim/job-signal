"""
JobSignal — Configuration and environment settings.

All values are loaded from a .env file at the project root.
Never hardcode secrets; always use this settings module.
"""

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from environment variables.

    Every attribute maps to a variable in the .env file.
    Pydantic-settings will raise a validation error on startup
    if a required variable is missing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/jobsignal",
        description="Full SQLAlchemy-compatible PostgreSQL connection string.",
    )

    # ── JSearch (RapidAPI) ───────────────────────────────────────────────────
    rapidapi_key: str = Field(
        default="",
        description="Your RapidAPI key — used by the JSearch client.",
    )

    # ── Adzuna ────────────────────────────────────────────────────────────────
    adzuna_app_id: str = Field(
        default="",
        description="Adzuna application ID.",
    )
    adzuna_app_key: str = Field(
        default="",
        description="Adzuna application key.",
    )

    # ── Anthropic (future modules) ────────────────────────────────────────────
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API key — used in processing/analysis modules.",
    )

    # ── Ingestion behaviour ───────────────────────────────────────────────────
    default_search_queries: List[str] = Field(
        default=[
            "AI Engineer",
            "LLM Engineer",
            "Machine Learning Engineer",
            "Prompt Engineer",
            "AI Research Engineer",
        ],
        description="Search queries used by the orchestrator if none are provided.",
    )

    adzuna_countries: List[str] = Field(
        default=["us", "gb"],
        description="Country codes to query on Adzuna.",
    )

    ingestion_max_results_per_query: int = Field(
        default=10,
        description="Maximum number of results to fetch per query per API.",
    )

    # ── Groq (LLM) ───────────────────────────────────────────────────────────
    groq_api_key: str = Field(
        default="",
        description="Groq API key for llama-3.3-70b-versatile.",
    )

    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="The Groq model used for parsing and scoring.",
    )

    # ── Scheduler ─────────────────────────────────────────────────────────────
    schedule_interval_hours: int = Field(
        default=24,
        description="How often (in hours) the scheduled ingestion runs.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call).

    Usage:
        from jobsignal.config.settings import get_settings
        settings = get_settings()
    """
    # Fix broken SSL cert path if encountered in some Conda/Windows environments
    import os
    try:
        import certifi
        if "SSL_CERT_FILE" not in os.environ or not os.path.exists(os.environ.get("SSL_CERT_FILE", "")):
            os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass
        
    return Settings()
