# AI Lead Scoring Agent

FastAPI service that researches a submitted person and company, records source-linked evidence, extracts structured facts, and calculates a deterministic lead score from 0 to 100. Form claims remain probable until public evidence verifies them.

## Core capabilities

- Bounded research across official websites, Wikipedia, optional SEC EDGAR data, and optional SearXNG search
- SSRF-aware URL validation, safe redirects, robots rules, timeouts, retries, rate limits, and response size limits
- LangChain and OpenAI structured fact extraction with verified, probable, unknown, and conflicting states
- Configuration-driven weights and HOT, WARM, and COLD thresholds
- Source attribution and separate research and scoring confidence
- Async PostgreSQL persistence with Alembic, plus in-memory development mode

## Architecture

```text
Lead Form
   |
FastAPI
   |
Lead Service
   |
Research Orchestrator
   |
Public Data + Selective Website Research
   |
Evidence -> Structured Fact Extraction
   |
Deterministic Scoring Engine
   |
Lead Score + Sources + Confidence
```

Research, evidence, fact extraction, and scoring are separate layers. The LLM interprets evidence but never assigns the final score.

## Project structure

```text
app/
  api/             Thin HTTP routes and dependencies
  agents/          Structured fact extraction
  core/            Settings, errors, logging, middleware
  db/              SQLAlchemy models and database lifecycle
  providers/       Website, public data, and search providers
  repositories/    In-memory and SQL repositories
  research/        Provider contracts and orchestration
  schemas/         API request and response models
  scoring/         Deterministic rules and scoring profile
  services/        Lead scoring use case
alembic/            Database migrations
tests/              Unit and integration tests
```

`template.py` is the idempotent project structure initializer used to create this layout.

## Environment variables

Copy `.env.example` to `.env`. Important values include:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI credential. Required when `REQUIRE_LLM=true`. |
| `OPENAI_MODEL` | Structured extraction model. |
| `DATABASE_URL` | PostgreSQL or SQLite connection URL. Empty uses in-memory storage. |
| `SEARCH_PROVIDER` | `none` or `searxng`. |
| `SEARCH_BASE_URL` | Base URL of the configured SearXNG instance. |
| `SEC_USER_AGENT` | SEC-compliant identity string. Empty disables SEC requests. |
| `MAX_RESEARCH_SOURCES` | Maximum evidence sources per request. |
| `MAX_RESEARCH_PAGES` | Maximum website pages per request. |
| `HOT_SCORE_THRESHOLD` | Minimum HOT score. |
| `WARM_SCORE_THRESHOLD` | Minimum WARM score. |
| `SCORE_WEIGHT_*` | Six category weights that must total 100. |
| `TARGET_INDUSTRIES` | Comma-separated default target industries. |

Without an OpenAI key, development mode uses a conservative rule-based extractor and reports that fallback in `research_warnings`.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` and copy with `Copy-Item .env.example .env`.

## Running the API

```bash
uvicorn app.main:app --reload
```

OpenAPI documentation is available at `/docs`. Render uses `/health` for health checks.

## Testing and quality checks

```bash
pytest
ruff check .
ruff format --check .
mypy app tests
```

Tests use fakes and mocked transports. They do not require credentials or network access.

## Render deployment

`Dockerfile` runs the API as a non-root user and binds Uvicorn to Render's `PORT`. `render.yaml` provisions the web service and PostgreSQL database and runs `alembic upgrade head` before deployment. Set `OPENAI_API_KEY` as a secret in Render.

## Example request

```bash
curl -X POST http://localhost:8000/api/v1/leads/score \
  -H "Content-Type: application/json" \
  -d '{
    "name": "John Smith",
    "company": "ABC Technologies",
    "designation": "CEO",
    "email": "john@example.com",
    "website": "https://example.com",
    "industry": "SaaS",
    "target_profile": {
      "industries": ["SaaS"],
      "min_employees": 50
    }
  }'
```

## Example response

```json
{
  "lead_id": "lead_0123456789abcdef0123456789abcdef",
  "score": 87,
  "classification": "HOT",
  "research_confidence": 0.82,
  "scoring_confidence": 0.86,
  "summary": "HOT lead with the strongest contribution from decision maker. The score is deterministic and evidence confidence is reported separately.",
  "factors": [
    {
      "name": "Decision Maker",
      "score": 30.0,
      "max_score": 30,
      "reason": "The role is assessed as top executive; verification status is verified.",
      "confidence": 0.95,
      "evidence_ids": ["ev_a1b2c3d4"]
    }
  ],
  "facts": [],
  "sources": [],
  "research_warnings": [],
  "created_at": "2026-08-30T12:00:00Z"
}
```

The real response includes all six factors, extracted facts, evidence excerpts, and source URLs.
