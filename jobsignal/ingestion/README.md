# Ingestion Module

Handles all data fetching from external job posting APIs.

## Components

- `clients/jsearch.py` — JSearch API client (via RapidAPI)
- `clients/adzuna.py` — Adzuna API client
- `clients/remotive.py` — Remotive free API client
- `schemas.py` — Unified `JobPost` Pydantic schema
- `orchestrator.py` — Calls all clients, deduplicates, saves to DB
- `scheduler.py` — APScheduler wrapper for 24-hour automated runs
