# RTM-and-Quality-Prediction-backend

FastAPI backend for the RTM Generation Service: test-case quality
prediction, coverage-gap detection, risk-based prioritization, and a live
Requirements Traceability Matrix (RTM), built as part of the NextGen QA
end-to-end Software Testing Lifecycle automation framework.

## What it does

- **Test Inventory** — a unified catalogue of generated/executed test
  cases across frameworks, linked to their requirement and acceptance
  criterion.
- **Quality Prediction** — scores each test case using a weighted formula
  (assertion strength, coverage, boundary coverage, error handling,
  mutation resistance) cross-checked against a trained RandomForest model.
- **Coverage Gap Detection** — runs the appropriate coverage tool for a
  repository (via a GitHub-integrated coverage agent) and maps results
  back to acceptance criteria.
- **Risk-Based Prioritization** — ranks coverage gaps using an explainable,
  keyword- and history-based risk classifier (Critical/High/Medium/Low).
- **Live RTM** — keeps requirement → acceptance criteria → test case →
  execution → coverage status continuously up to date from real execution
  events, rather than a manually maintained spreadsheet.
- **Intelligent Test Improvement** — recommends concrete improvements for
  low-quality, gapped, or high-risk tests for engineer review.

## Tech stack

- **FastAPI** + **SQLAlchemy** + **PostgreSQL**
- **scikit-learn** (RandomForest) for quality prediction
- GitHub-integrated coverage runners for Python, JavaScript/TypeScript,
  and Java projects

## Setup

1. Create and activate a virtual environment (Python 3.11):
   ```bash
   python3.11 -m venv venv
   source venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in `DATABASE_URL` (PostgreSQL)
   and any optional integration settings (GitHub token, Component 1/2 API
   URLs).
4. Start the API (tables are created automatically on startup):
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
5. Check it's running:
   ```bash
   curl http://localhost:8000/api/health
   ```

`init_db.sql` is provided as an optional reference for the raw SQL schema;
it is not required for normal use. `app/seed.py` can be run
(`python -m app.seed`) to populate sample data for local development.
