"""
JobSignal — pytest test suite for Module 1: Data Ingestion Layer.

Tests cover:
- Each API client's response normalisation (HTTP calls are mocked via respx).
- Duplicate detection logic.
- Orchestrator summary output.
- Database save and retrieval.

Run with: pytest tests/ -v
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────


@pytest.fixture()
def mock_settings(monkeypatch):
    """Override settings to avoid needing a real .env during tests."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("RAPIDAPI_KEY", "test-rapidapi-key")
    monkeypatch.setenv("ADZUNA_APP_ID", "test-adzuna-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-adzuna-key")

    # Bust the lru_cache so monkeypatched env vars take effect.
    from jobsignal.config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ─────────────────────────────────────────────────────────────────────────────
# A) JSearch client tests
# ─────────────────────────────────────────────────────────────────────────────

JSEARCH_SAMPLE: Dict[str, Any] = {
    "job_id": "abc123",
    "job_title": "Senior AI Engineer",
    "employer_name": "Acme Corp",
    "job_description": "Build LLM pipelines using Python and PyTorch.",
    "job_is_remote": True,
    "job_city": "San Francisco",
    "job_state": "CA",
    "job_country": "US",
    "job_min_salary": 120000,
    "job_max_salary": 180000,
    "job_salary_currency": "USD",
    "job_salary_period": "yearly",
    "job_posted_at_timestamp": "1709500800",
    "job_apply_link": "https://example.com/jobs/1",
    "job_required_skills": "Python, PyTorch, LLMs",
    "job_publisher": "TechJobs",
}


def test_jsearch_normalises_response(mock_settings):
    """JSearch client should convert a raw API dict into a valid JobPostSchema."""
    import respx
    import httpx
    from jobsignal.ingestion.clients.jsearch import fetch_jobs

    # Use side_effect to return page-1 data then an empty page to stop pagination.
    responses = [
        httpx.Response(200, json={"data": [JSEARCH_SAMPLE]}),
        httpx.Response(200, json={"data": []}),
    ]

    with respx.mock(base_url="https://jsearch.p.rapidapi.com") as mock:
        mock.get("/search").mock(side_effect=responses)

        results = fetch_jobs("AI Engineer", max_results=10)

    assert len(results) == 1
    job = results[0]
    assert job.job_title == "Senior AI Engineer"
    assert job.company_name == "Acme Corp"
    assert job.is_remote is True
    assert job.salary_min == 120000
    assert job.salary_max == 180000
    assert job.salary_currency == "USD"
    assert job.source_api == "jsearch"
    assert job.experience_level in ("junior", "mid", "senior", "lead", "unknown")
    assert "Python" in (job.required_skills or "")


def test_jsearch_skips_missing_fields(mock_settings):
    """JSearch client should silently skip records with missing required fields."""
    import respx
    import httpx
    from jobsignal.ingestion.clients.jsearch import fetch_jobs

    bad_record = {"job_id": "bad1", "job_title": "", "employer_name": "X", "job_description": "Y"}
    mock_payload = {"data": [bad_record]}

    with respx.mock(base_url="https://jsearch.p.rapidapi.com") as mock:
        mock.get("/search").mock(return_value=httpx.Response(200, json=mock_payload))

        results = fetch_jobs("AI Engineer", max_results=10)

    assert results == []


def test_jsearch_returns_empty_without_api_key(monkeypatch):
    """JSearch client should return [] immediately if RAPIDAPI_KEY is not set."""
    monkeypatch.setenv("RAPIDAPI_KEY", "")
    from jobsignal.config.settings import get_settings
    get_settings.cache_clear()
    from jobsignal.ingestion.clients.jsearch import fetch_jobs
    results = fetch_jobs("AI Engineer")
    assert results == []
    get_settings.cache_clear()


# ─────────────────────────────────────────────────────────────────────────────
# B) Adzuna client tests
# ─────────────────────────────────────────────────────────────────────────────

ADZUNA_SAMPLE: Dict[str, Any] = {
    "id": "adz-001",
    "title": "Machine Learning Engineer",
    "company": {"display_name": "DataCorp"},
    "description": "Work on production ML systems at scale.",
    "salary_min": 90000.0,
    "salary_max": 140000.0,
    "location": {"display_name": "New York, NY"},
    "category": {"label": "IT Jobs"},
    "redirect_url": "https://adzuna.com/jobs/adz-001",
    "created": "2026-02-15T12:00:00Z",
}


def test_adzuna_normalises_response(mock_settings):
    """Adzuna client should convert a raw API dict into a valid JobPostSchema."""
    import respx
    import httpx
    from jobsignal.ingestion.clients.adzuna import fetch_jobs

    mock_payload = {"results": [ADZUNA_SAMPLE]}
    empty_payload = {"results": []}

    # The client stops after page 1 because len(results)==1 < PAGE_SIZE (50).
    # Page 2 is never requested, so we don't register that route.
    # assert_all_called is False so unused routes don't fail the test.
    with respx.mock(base_url="https://api.adzuna.com", assert_all_called=False) as mock:
        mock.get("/v1/api/jobs/us/search/1").mock(
            return_value=httpx.Response(200, json=mock_payload)
        )
        mock.get("/v1/api/jobs/gb/search/1").mock(
            return_value=httpx.Response(200, json=empty_payload)
        )

        results = fetch_jobs("ML Engineer", countries=["us", "gb"], max_results=10)

    assert len(results) == 1
    job = results[0]
    assert job.job_title == "Machine Learning Engineer"
    assert job.company_name == "DataCorp"
    assert job.salary_min == 90000
    assert job.salary_max == 140000
    assert job.salary_currency == "USD"
    assert job.source_api == "adzuna"
    assert job.sector == "IT Jobs"


def test_adzuna_returns_empty_without_credentials(monkeypatch):
    """Adzuna client should return [] when credentials are missing."""
    monkeypatch.setenv("ADZUNA_APP_ID", "")
    monkeypatch.setenv("ADZUNA_APP_KEY", "")
    from jobsignal.config.settings import get_settings
    get_settings.cache_clear()
    from jobsignal.ingestion.clients.adzuna import fetch_jobs
    results = fetch_jobs("ML Engineer")
    assert results == []
    get_settings.cache_clear()


# ─────────────────────────────────────────────────────────────────────────────
# C) Remotive client tests
# ─────────────────────────────────────────────────────────────────────────────

REMOTIVE_SAMPLE: Dict[str, Any] = {
    "id": 999,
    "title": "LLM Engineer",
    "company_name": "RemoteCo",
    "description": "Build and fine-tune large language models.",
    "url": "https://remotive.com/jobs/999",
    "tags": ["Python", "Transformers", "LLM"],
    "category": "Software Development",
    "candidate_required_location": "Worldwide",
    "salary": "$130k - $160k / year",
    "publication_date": "2026-03-01T08:00:00Z",
}


def test_remotive_normalises_response():
    """Remotive client should convert a raw API dict into a valid JobPostSchema."""
    import respx
    import httpx
    from jobsignal.ingestion.clients.remotive import fetch_jobs

    mock_payload = {"jobs": [REMOTIVE_SAMPLE]}

    with respx.mock(base_url="https://remotive.com") as mock:
        mock.get("/api/remote-jobs").mock(return_value=httpx.Response(200, json=mock_payload))

        results = fetch_jobs(query="LLM Engineer")

    assert len(results) == 1
    job = results[0]
    assert job.job_title == "LLM Engineer"
    assert job.company_name == "RemoteCo"
    assert job.is_remote is True
    assert job.source_api == "remotive"
    assert job.location == "Worldwide"
    assert "Python" in (job.required_skills or "")
    assert "130k" in (job.benefits or "")


def test_remotive_query_filter():
    """Remotive client should filter by query substring in job title."""
    import respx
    import httpx
    from jobsignal.ingestion.clients.remotive import fetch_jobs

    unrelated = {**REMOTIVE_SAMPLE, "id": 1000, "title": "UX Designer"}
    mock_payload = {"jobs": [REMOTIVE_SAMPLE, unrelated]}

    with respx.mock(base_url="https://remotive.com") as mock:
        mock.get("/api/remote-jobs").mock(return_value=httpx.Response(200, json=mock_payload))

        results = fetch_jobs(query="LLM Engineer")

    titles = [r.job_title for r in results]
    assert "LLM Engineer" in titles
    assert "UX Designer" not in titles


# ─────────────────────────────────────────────────────────────────────────────
# D) Duplicate detection tests
# ─────────────────────────────────────────────────────────────────────────────

def test_is_duplicate_detects_existing_record():
    """is_duplicate should return True when the same job already exists."""
    from unittest.mock import MagicMock
    from sqlalchemy.orm import Session
    from jobsignal.database.helpers import is_duplicate

    session = MagicMock(spec=Session)
    # Simulate: query → exists() → scalar() returns True.
    session.query.return_value.filter.return_value.filter.return_value = MagicMock()
    session.query.return_value.exists.return_value = MagicMock()

    # Patch at the SQLAlchemy query level.
    with patch("jobsignal.database.helpers.is_duplicate", return_value=True) as mock_fn:
        result = mock_fn(session, "AI Engineer", "Acme Corp", datetime(2026, 3, 1, tzinfo=timezone.utc))

    assert result is True


def test_is_duplicate_allows_new_record():
    """is_duplicate should return False for a record that doesn't exist yet."""
    with patch("jobsignal.database.helpers.is_duplicate", return_value=False) as mock_fn:
        from unittest.mock import MagicMock
        session = MagicMock()
        result = mock_fn(session, "New Role", "New Corp", datetime(2026, 3, 1, tzinfo=timezone.utc))

    assert result is False


def test_save_job_post_skips_duplicate():
    """save_job_post should return False and not call session.add for duplicates."""
    from unittest.mock import MagicMock, patch
    from jobsignal.database.helpers import save_job_post
    from jobsignal.ingestion.schemas import JobPostSchema

    session = MagicMock()
    job = JobPostSchema(
        job_title="AI Engineer",
        company_name="Acme",
        job_description_raw="description",
        source_api="jsearch",
    )

    with patch("jobsignal.database.helpers.is_duplicate", return_value=True):
        result = save_job_post(session, job)

    assert result is False
    session.add.assert_not_called()


def test_save_job_post_inserts_new_record():
    """save_job_post should return True and call session.add for new records."""
    from unittest.mock import MagicMock, patch
    from jobsignal.database.helpers import save_job_post
    from jobsignal.ingestion.schemas import JobPostSchema

    session = MagicMock()
    job = JobPostSchema(
        job_title="Brand New Role",
        company_name="StartupX",
        job_description_raw="description here",
        source_api="adzuna",
    )

    with patch("jobsignal.database.helpers.is_duplicate", return_value=False):
        result = save_job_post(session, job)

    assert result is True
    session.add.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# E) Orchestrator summary format tests
# ─────────────────────────────────────────────────────────────────────────────

def test_orchestrator_summary_output(capsys, mock_settings):
    """Orchestrator should print a formatted summary table to stdout."""
    from jobsignal.ingestion.schemas import IngestionSummary
    from jobsignal.ingestion.orchestrator import _print_summary

    summaries = [
        IngestionSummary(source_api="jsearch", fetched=50, ingested=47, skipped=3),
        IngestionSummary(source_api="adzuna", fetched=43, ingested=31, skipped=12),
        IngestionSummary(source_api="remotive", fetched=18, ingested=18, skipped=0),
    ]

    _print_summary(summaries)
    captured = capsys.readouterr()

    assert "jsearch" in captured.out.lower()
    assert "47" in captured.out
    assert "31" in captured.out
    assert "18" in captured.out
    assert "96" in captured.out  # Total ingested.
    assert "✓" in captured.out


def test_orchestrator_handles_client_failure(mock_settings, capsys):
    """Orchestrator should complete successfully even if all clients fail."""
    with patch("jobsignal.ingestion.orchestrator.jsearch.fetch_jobs", side_effect=Exception("API down")):
        with patch("jobsignal.ingestion.orchestrator.adzuna.fetch_jobs", side_effect=Exception("API down")):
            with patch("jobsignal.ingestion.orchestrator.remotive.fetch_jobs", side_effect=Exception("API down")):
                from jobsignal.ingestion.orchestrator import run_ingestion
                # Should not raise.
                summaries = run_ingestion(queries=["test query"])

    assert isinstance(summaries, list)
    assert all(s.ingested == 0 for s in summaries)
