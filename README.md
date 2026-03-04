# JobSignal

**AI-powered job market intelligence and autonomous job hunting pipeline.**

## Overview

JobSignal is a local-first application that:
- Pulls job postings from multiple APIs (JSearch, Adzuna, Remotive)
- Extracts structured intelligence from job descriptions with AI
- Analyzes market trends and in-demand skills
- Tailors resumes and cover letters per job post
- Automates job applications and follow-up outreach

## Module Structure

| Module | Package | Status |
|--------|---------|--------|
| 1 — Data Ingestion | `jobsignal/ingestion/` | ✅ Complete |
| 2 — Processing | `jobsignal/processing/` | 🔜 Planned |
| 3 — Analysis | `jobsignal/analysis/` | 🔜 Planned |
| 4 — Dashboard | `jobsignal/dashboard/` | 🔜 Planned |
| 5 — Ideation | `jobsignal/ideation/` | 🔜 Planned |
| 6 — Resume | `jobsignal/resume/` | 🔜 Planned |
| 7 — Applications | `jobsignal/applications/` | 🔜 Planned |
| 8 — Outreach | `jobsignal/outreach/` | 🔜 Planned |
| 9 — CRM | `jobsignal/crm/` | 🔜 Planned |

## Quickstart (Module 1)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy and fill in environment variables
copy .env.example .env
# Edit .env with your API keys and DB credentials

# 3. Create the PostgreSQL database
createdb jobsignal

# 4. Run Alembic migrations
alembic upgrade head

# 5. Run a single ingestion pass
python main.py ingest

# 6. Check status
python main.py status

# 7. Start the 24-hour scheduled ingestion
python main.py ingest --schedule
```

## Running Tests

```bash
pytest tests/ -v
```

## Tech Stack

- **Backend**: Python + FastAPI
- **Database**: PostgreSQL + SQLAlchemy ORM + Alembic
- **Scheduling**: APScheduler
- **HTTP**: httpx + tenacity (retry/backoff)
- **Logging**: loguru
- **Config**: pydantic-settings + python-dotenv
- **UI** *(future)*: Streamlit
