# PriceScope India

Exact-variant product price comparison across Amazon India, Flipkart, Blinkit, Zepto and BigBasket.
Paste a product URL, enter a 6-digit PIN code, and compare the same product (same size, quantity,
pack count and variant) with transparent final prices.

> **Integration status:** no marketplace integration is live. Every marketplace starts as
> *not configured* (Amazon, Flipkart) or *unsupported* (Blinkit, Zepto, BigBasket: no public API).
> Demo mode (`PRICESCOPE_DEMO_MODE=true`) uses clearly labelled sample data.
> See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

> **Storage:** data is stored in **Google Sheets** for now (one tab per table), through a storage
> interface that can switch back to PostgreSQL with one setting. Setup and limits:
> [docs/STORAGE.md](docs/STORAGE.md).

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Repo setup, database schema + migrations, backend skeleton, design system | ✅ done |
| 1b | Google Sheets storage backend (interim), shared validation, contract tests | ✅ done |
| 2 | Homepage form: product-link recognition + PIN-code validation (no price lookups yet) | ✅ done |
| 3 | SSRF-safe short-link resolution; quantity / pack / variant normalization | ✅ done |
| 4 | Adapter framework, demo + official-shell adapters, concurrent fetches (threads / Celery), matching, pricing, **card offers**, comparison page | ✅ done |
| 5 | Matching engine: barcode check digits, model/brand normalisation + aliases, fuzzy titles, optional AI review | ✅ done |
| 6–9 | See the implementation plan | pending |

## Repository layout

```
backend/        FastAPI app (Python 3.12), SQLAlchemy models, Alembic migrations
frontend/       Next.js 15 + TypeScript + Tailwind v4 + shadcn/ui
database/       Postgres init scripts, schema notes
docs/           Plan and design docs
tests/          Backend unit + integration tests (pytest)
integrations/   Marketplace adapters (installable package, independent of the backend)
workers/        Celery tasks: marketplace I/O only
```

## Prerequisites

- A Google Cloud service account and a spreadsheet shared with it ([docs/STORAGE.md](docs/STORAGE.md))
- Docker Desktop (Redis 7; PostgreSQL 16 only if you use the `postgres` backend or run its tests)
- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 automatically)
- Node.js 20+ and npm

## Local setup

```powershell
Copy-Item .env.example .env
```

Fill in the Google Sheets values in `.env` (see [docs/STORAGE.md](docs/STORAGE.md)), then:

```powershell
cd backend; uv sync; uv run python -m app.storage.bootstrap
```

```powershell
cd backend; uv run uvicorn app.main:app --reload --port 8000
```

```powershell
cd frontend; npm install; npm run dev
```

- Web: <http://localhost:3000>
- API docs (Swagger): <http://localhost:8000/docs> · ReDoc: <http://localhost:8000/redoc>
- Readiness: <http://localhost:8000/api/v1/health/ready>

Use `127.0.0.1` (not `localhost`) in `PRICESCOPE_DATABASE_URL` on Windows: `localhost` tries
IPv6 first and adds a multi-second stall per connection.

## Checks

```powershell
cd backend; uv run ruff check app alembic ../tests; uv run mypy; uv run pytest
```

```powershell
cd frontend; npm run lint; npm run typecheck; npm test; npm run build
```

Storage tests run against an in-memory fake spreadsheet, so they need no Google account. Tests marked `db` create and drop a throwaway database on the configured PostgreSQL server,
so your development data is never touched. They are skipped if PostgreSQL is unreachable.

## Database migrations

```powershell
cd backend; uv run alembic revision --autogenerate -m "describe change"
```

Always review generated migrations. `tests/integration/test_migrations.py` fails if the models and
migrations drift apart, and checks a full upgrade → downgrade → upgrade cycle.

## Security notes

- All secrets come from environment variables; `.env` is git-ignored.
- `integration_credentials` stores only references (`env:NAME`, `aws-sm:…`), enforced by a
  database CHECK constraint. It is never exposed by the API.
- `PRICESCOPE_AUTH_MODE=dev` is refused at startup when `PRICESCOPE_ENV=production`.
- Only `NEXT_PUBLIC_*` variables reach the browser; never put secrets there.

Deployment instructions (Vercel + Render/AWS) arrive in Phase 9.
