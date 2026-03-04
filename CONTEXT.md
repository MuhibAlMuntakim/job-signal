# JobSignal Project Context

## Project Status: Module 1B Complete ✅
Module 1B (Resume Intelligence + Streamlit UI) has been successfully implemented and integrated with Module 1 (Data Ingestion).

## Folder Tree Snapshot
```text
.
├── alembic/
│   ├── versions/
│   │   ├── 0001_initial_job_posts.py
│   │   └── 20260304_1634_7758a8e2f863_add_candidate_profiles_and_job_scores_.py
│   └── env.py
├── jobsignal/
│   ├── analysis/
│   │   ├── __init__.py
│   │   └── scorer.py           <-- NEW: Job Scoring Engine
│   ├── config/
│   │   ├── rate_limiter.py     <-- NEW: Groq RPM Limiter
│   │   └── settings.py         <-- UPDATED: Groq Config
│   ├── dashboard/
│   │   ├── __init__.py
│   │   └── app.py              <-- NEW: Streamlit UI
│   ├── database/
│   │   ├── models.py           <-- UPDATED: Profile/Score Tables
│   │   └── session.py
│   ├── ingestion/
│   │   ├── keyword_generator.py <-- NEW: Dynamic Keyword Gen
│   │   └── orchestrator.py
│   └── resume/
│       ├── __init__.py
│       └── parser.py           <-- NEW: PDF Parser + LLM
├── .streamlit/
│   └── config.toml             <-- NEW: UI Theme
├── tests/
│   ├── test_keyword_generator.py
│   ├── test_resume_parser.py
│   └── test_scorer.py
├── main.py
└── requirements.txt            <-- UPDATED: groq, pymupdf, streamlit
```

## Key Infrastructure
- **LLM**: Groq (`llama-3.3-70b-versatile`) used for resume parsing, keyword generation, and skill/sector scoring.
- **Rate Limiting**: Custom `RateLimiter` enforces 30 RPM (safe buffer 25 RPM) for Groq.
- **Database**: PostgreSQL with `CandidateProfile` (resume data) and `JobScore` (match results) tables.
- **Environment**: Conda environment `js` (located at `C:\Users\user\.conda\envs\js`).
- **UI**: Streamlit dashboard with "My Profile" (upload), "Top Matches" (ranked list), and "Market Intel" (planned).

## Documentation
- [Implementation Plan](file:///C:/Users/user/.gemini/antigravity/brain/b740db69-f0f0-4349-8900-69241baa7d6e/implementation_plan.md)
- [Walkthrough](file:///C:/Users/user/.gemini/antigravity/brain/b740db69-f0f0-4349-8900-69241baa7d6e/walkthrough.md)
