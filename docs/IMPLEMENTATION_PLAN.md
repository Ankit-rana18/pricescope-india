# PriceScope India — Implementation Plan

Status: **Phases 1–5 complete** (2026-11-24). Phases 6–9 pending. Storage is Google Sheets for now (see docs/STORAGE.md).

## 0. Repository inspection

- `C:\Users\user\Documents\price_comparesion` was **empty**: no files, no git repository, nothing to keep.
- Tools installed on this machine: Node 24.22, npm 11.19, Python 3.15.1, Docker 29.9, git 2.56. PostgreSQL and Redis are not installed, so they will run through `docker-compose`.
- Python 3.15 is very new, and some compiled packages (asyncpg, pydantic-core, psycopg) may not have wheels for it yet. The backend will be pinned to **Python 3.12** in Docker and in `.python-version`. Local development without Docker will need Python 3.12 through `uv` or the `py` launcher.
- Celery does not officially support Windows. Workers will run in Docker; running a worker natively on Windows needs `--pool=solo` and is only meant for debugging.

---

## 1. Constraints that shape the design

These come from the brief's honesty rules, and they affect the architecture more than anything else.

| Marketplace | What legitimate access exists | What the adapter does on day one |
|---|---|---|
| **Amazon India** | Amazon Creators API, available to Associates who meet the sales and eligibility thresholds. | A real adapter shell with the request and signing layer behind an interface. Its status is `NOT_CONFIGURED` until credentials are added and a live call succeeds. No endpoint is hard-coded until it is confirmed against the official docs you have access to. |
| **Flipkart** | The Flipkart Affiliate API and product feeds, for approved affiliates. These are not location-aware, so they give no PIN-specific price. | Adapter shell, `NOT_CONFIGURED`. Even once it is live, location capability is `NONE`, so the PIN status shows "not verifiable". |
| **Blinkit / Zepto / BigBasket** | No public product API. Access is only possible through a partnership or a licensed data provider. | A provider adapter interface with no concrete implementation. Status is `UNSUPPORTED` until a provider is chosen. |

What follows from this:

1. **URL extraction will not scrape marketplace pages.** Fetching Amazon or Flipkart HTML breaks their terms and runs into bot protection. Extraction will parse identifiers out of the URL itself (Amazon ASIN, Flipkart `pid`/item ID, BigBasket product ID, Blinkit/Zepto product slugs or IDs), then load product details through that marketplace's authorized adapter, or the mock adapter in demo mode.
2. Short links (`amzn.in`, `amzn.to`, `dl.flipkart.com`) are the only case where the backend makes an outbound request. That request is a redirect-only resolution through the **SSRF-safe HTTP client** (§7). Redirects are followed step by step, every hop is re-validated, and the body is never read.
3. **Demo mode** (`PRICESCOPE_DEMO_MODE=true`) turns on mock adapters for all five marketplaces. Every demo result carries `data_source: "DEMO"`, and the UI shows a persistent "Demo data — not real prices" banner and a badge on each row. Demo and live data are never mixed in one comparison.
4. The default ranking includes only results where `match = EXACT`, the item is available, and the final price is fully known. Results with any unknown charge are shown as "final price incomplete" and listed after the fully verified ones.

---

## 2. Architecture

```
                  ┌──────────────────────────┐
 Browser ───────▶ │ Next.js (Vercel)         │  Supabase Auth (JWT, browser session)
                  │ App Router, RSC, shadcn  │
                  └────────────┬─────────────┘
                               │ HTTPS + Bearer JWT
                  ┌────────────▼─────────────┐
                  │ FastAPI (Render/AWS)     │──▶ PostgreSQL (SQLAlchemy 2 + Alembic)
                  │  /api/v1, OpenAPI        │──▶ Redis (cache, rate limits, Celery broker)
                  └────────────┬─────────────┘
                               │ Celery group (one task per marketplace)
                  ┌────────────▼─────────────┐
                  │ Celery workers           │──▶ integrations/* adapters
                  │  timeouts, retries,      │       (Amazon, Flipkart, Blinkit,
                  │  backoff, chord callback │        Zepto, BigBasket, Mock)
                  └──────────────────────────┘
```

**How a comparison runs**

1. `POST /api/v1/comparisons {url, pincode}` validates the input, rate-limits the request, and parses the URL into `{marketplace, external_id}`.
2. It checks the Redis cache key `cmp:{marketplace}:{external_id}:{pincode}` (TTL 10 minutes). On a hit, it returns the existing comparison.
3. On a miss, it creates a `comparisons` row (`status=PENDING`), fans out a Celery `group` with one `search_marketplace` task per enabled adapter, and returns `202 {comparison_id}`.
4. Each task resolves the source product, searches its marketplace, scores candidates with the matching engine, checks location where the adapter supports it, prices the result through the price service, and writes a `comparison_results` row. Each task has a soft time limit of 12 s and a hard limit of 15 s, 3 retries with exponential backoff and jitter, and retries only on transient errors.
5. A chord callback sets the comparison to `COMPLETE` or `PARTIAL`. Failed adapters write a result with `status=FAILED` and an error code instead of raising, so one failure never takes down the whole comparison.
6. The frontend polls `GET /comparisons/{id}`, backing off from 1 s to 3 s. SSE can be added later. Results render as they arrive. "Retry" on a failed marketplace calls `POST /comparisons/{id}/retry?marketplace=…`.

---

## 3. Folder structure

```
price_comparesion/
├── README.md                     setup, demo mode, deployment
├── docker-compose.yml            postgres, redis, api, worker, beat, frontend
├── .env.example                  every variable, no real values
├── .gitignore  .editorconfig
├── docs/
│   ├── IMPLEMENTATION_PLAN.md    (this file)
│   ├── ARCHITECTURE.md
│   ├── INTEGRATIONS.md           how to activate each marketplace legitimately
│   ├── MATCHING.md               matching rules and thresholds
│   ├── SECURITY.md
│   └── DEPLOYMENT.md             Vercel, Render, AWS
├── frontend/                     Next.js 15, TypeScript, Tailwind v4, shadcn/ui
│   ├── app/
│   │   ├── (marketing)/page.tsx              homepage, URL + PIN form
│   │   ├── compare/[id]/page.tsx             comparison dashboard
│   │   ├── products/[slug]/page.tsx          SEO product page + price history
│   │   ├── categories/[slug]/page.tsx        SEO category page
│   │   ├── history/  saved/  alerts/  account/
│   │   ├── admin/ (users, integrations, health, activity, errors)
│   │   ├── auth/ (login, callback)
│   │   ├── sitemap.ts  robots.ts
│   ├── components/ (ui/ = shadcn, compare/, product/, layout/, charts/)
│   ├── lib/ (api-client.ts, supabase/, validators.ts, format.ts)
│   └── tests/ (vitest + Testing Library, Playwright e2e)
├── backend/
│   ├── pyproject.toml            uv-managed, Python 3.12
│   ├── alembic/ (versions/)      ← "database migrations" live here
│   └── app/
│       ├── main.py               app factory, middleware, routers
│       ├── core/ (config.py, logging.py, security.py, errors.py, rate_limit.py, deps.py)
│       ├── api/v1/ (comparisons, products, marketplaces, location, search, saved, alerts, admin)
│       ├── schemas/              Pydantic request/response models
│       ├── models/               SQLAlchemy ORM models
│       ├── repositories/         data access (no SQL in routers)
│       └── services/
│           ├── url_parser.py     identifier extraction + SSRF-safe short-link resolution
│           ├── safe_http.py      SSRF-guarded httpx client
│           ├── normalization.py  units, quantities, pack counts, colours
│           ├── matching/         engine.py, rules.py, fuzzy.py, llm_review.py
│           ├── pricing.py        centralized final-price calculation
│           ├── pincode.py        format + India Post directory lookup
│           └── comparison.py     orchestration
├── integrations/                 installable package `pricescope_integrations`
│   ├── base.py                   MarketplaceAdapter protocol, capabilities, errors
│   ├── registry.py               builds adapters from config (DI)
│   ├── amazon/  flipkart/  blinkit/  zepto/  bigbasket/
│   └── mock/ (adapter.py, fixtures/*.json)   ← demo data, clearly labelled
├── workers/
│   ├── celery_app.py
│   ├── tasks/ (comparison.py, price_refresh.py, alerts.py, health.py)
│   └── beat_schedule.py
├── database/
│   ├── schema.md                 ERD + table notes
│   ├── seeds/ (marketplaces.sql, pincode_directory loader)
│   └── init/                     docker-entrypoint init (extensions)
└── tests/
    ├── unit/                     url, normalization, matching, pricing, pincode
    ├── integration/              API + DB + Celery eager, adapter failures/timeouts
    ├── fixtures/                 mock marketplace responses
    └── conftest.py
```

`integrations/` and `workers/` sit at the top level as the brief asks. They are installed into the backend image as local path dependencies, so the API, the worker and the tests all import the same code.

---

## 4. Database design (PostgreSQL 16)

All tables use a `uuid` primary key (`gen_random_uuid()`), plus `created_at` and `updated_at` as `timestamptz`. Money is stored as `numeric(12,2)` in INR and never as a float. **Unknown values are `NULL` with an explicit status column, never 0.**

| Table | Key columns | Constraints / indexes |
|---|---|---|
| `users` | `id` (= Supabase `auth.users.id`), email, display_name, role (`user`/`admin`), default_pincode | unique(email) |
| `marketplaces` | code (`AMAZON_IN`…), name, base_domains[], logo_path, is_enabled, capabilities jsonb | unique(code) |
| `products` | canonical brand, manufacturer, model, title, category, slug, image_url | unique(slug); idx(brand, model); trigram idx(title) |
| `product_variants` | product_id FK, size, colour, quantity_value, quantity_unit (`g`/`ml`/`unit`), pack_count, variant_key | unique(product_id, variant_key) |
| `product_identifiers` | variant_id FK, type (`GTIN13`/`EAN`/`UPC`/`ASIN`/`FSN`/`SKU`/`MPN`), value | unique(type, value); idx(value) |
| `marketplace_products` | marketplace_id FK, variant_id FK (nullable), external_id, url, title_raw, attributes jsonb, last_seen_at | unique(marketplace_id, external_id) |
| `comparisons` | user_id FK (nullable for anonymous), source_marketplace_product_id FK, pincode, status, data_mode (`LIVE`/`DEMO`), completed_at | idx(user_id, created_at desc); idx(pincode) |
| `comparison_results` | comparison_id FK, marketplace_id FK, marketplace_product_id FK (nullable), status (`OK`/`NOT_FOUND`/`FAILED`/`UNSUPPORTED`/`NOT_CONFIGURED`), match_class, match_score, match_reasons jsonb, price breakdown columns + `*_status`, final_price, final_price_complete bool, availability, eta_text, error_code, checked_at | unique(comparison_id, marketplace_id) |
| `price_history` | marketplace_product_id FK, pincode (nullable), price, mrp, final_price, data_mode, observed_at | idx(marketplace_product_id, observed_at desc). Plain table for now; partitioning by month can come later. |
| `location_checks` | marketplace_product_id FK, pincode, verification (`VERIFIED`/`UNVERIFIABLE`/`UNAVAILABLE`/`NEEDS_PRECISE_LOCATION`), serviceable bool null, eta, checked_at | idx(marketplace_product_id, pincode, checked_at desc) |
| `delivery_fees` | marketplace_id FK, fee_type (`DELIVERY`/`HANDLING`/`PLATFORM`/`SMALL_CART`/`OTHER`), amount, source (`API`/`PUBLISHED_POLICY`), conditions jsonb, effective_from, effective_to, source_url | idx(marketplace_id, fee_type, effective_from) |
| `saved_products` | user_id FK, variant_id FK, note | unique(user_id, variant_id) |
| `price_alerts` | user_id FK, variant_id FK, pincode, target_price, is_active, last_triggered_at | idx(is_active, variant_id) |
| `integration_credentials` | marketplace_id FK, key_name, secret_ref (an env var or secrets-manager ARN, **never the secret itself**), rotated_at | unique(marketplace_id, key_name). The table is never exposed through any API, and its columns hold references only. |
| `integration_health_logs` | marketplace_id FK, status, latency_ms, error_code, message, occurred_at | idx(marketplace_id, occurred_at desc) |
| `pincode_directory` *(extra)* | pincode, office, district, state | idx(pincode). Seeded from the India Post open dataset on data.gov.in. |
| `audit_logs` *(extra)* | actor_id, action, target, ip_hash, metadata, occurred_at | Required by the security section. |

Supabase handles authentication only. Application data stays in our own PostgreSQL, so Supabase is not a hard dependency. The backend creates or updates a `users` row the first time it sees a verified JWT.

---

## 5. Core services

### 5.1 URL parser (`services/url_parser.py`)
- Allows only `https`, plus `http` upgraded to `https`. Hosts must be on a fixed allowlist (`amazon.in`, `www.amazon.in`, `amzn.in`, `amzn.to`, `flipkart.com`, `dl.flipkart.com`, `blinkit.com`, `zeptonow.com`, `bigbasket.com`). Userinfo, non-default ports and IDN homographs are rejected.
- Extraction rules:
  - Amazon ASIN from `/dp/`, `/gp/product/` and `/gp/aw/d/`.
  - Flipkart from `/p/itm…` plus `pid=`.
  - BigBasket from `/pd/{id}/`.
  - Blinkit from `/prn/…/prid/{id}`.
  - Zepto from `/pn/…/pvid/{uuid}`.
- Tracking parameters are stripped and a canonical URL is stored.

### 5.2 Normalization (`services/normalization.py`)
- Parses quantities from titles and attributes: `500 g`, `0.5kg`, `1 L`, `1000ml`, `2 x 200 g`, `Pack of 3`, `6 N`, `200g (Pack of 2)`.
- Converts mass to grams, volume to millilitres and counts to units. `Decimal` is used throughout.
- Computes the total net quantity as `per_unit × pack_count` and keeps both values.
- Normalizes colours through a synonym map (for example "midnight black" maps to the black family, while the exact colour string is kept for strict comparison). Brands are casefolded with aliases ("HUL" → "Hindustan Unilever"). Electronics storage and RAM such as `8GB/256GB` are parsed as variant attributes.

### 5.3 Matching engine (`services/matching/`)
Matching is deterministic and the rules run in order. Each rule can veto a candidate.

1. **GTIN, EAN or UPC equal** (checksum-validated) → `EXACT`. Hard attribute conflicts are still checked; if one exists, the result drops to `MISMATCH` and the data conflict is logged.
2. **Hard vetoes** → `MISMATCH`:
   - brand differs
   - normalized quantity differs (tolerance 0, except rounding: 0.5 % for converted units)
   - pack count differs
   - model or MPN differs
   - colour, size or storage differs when both sides state it
3. **Model/MPN equal + brand equal + no conflicts + quantity equal** (where applicable) → `EXACT`.
4. **Brand equal + all known attributes equal + RapidFuzz `token_set_ratio` ≥ 90**, but a required attribute is missing on one side → `PROBABLE`.
5. Anything else that is not vetoed → `UNVERIFIED`.
6. **Optional LLM review** (off by default; `LLM_REVIEW_ENABLED`, Claude via the Anthropic SDK). It runs only on `PROBABLE` or `UNVERIFIED` candidates. The model returns structured JSON that cites which attributes match. It can **raise a result to `PROBABLE` at most, never to `EXACT`**, and **can never override a hard veto**.

Every decision stores `match_reasons`, for example `["gtin_equal", "pack_count_equal:2"]` or `["veto:quantity 500g≠1kg"]`, and the UI shows them.

### 5.4 Price service (`services/pricing.py`)
```
final = item_price − Σ(verified eligible discounts) + delivery + handling + platform + Σ(other mandatory)
```
- Each component is `Money | UNKNOWN | NOT_APPLICABLE`, with a `source` and an `assumption` note.
- If any mandatory component is `UNKNOWN`, the result is `final_price_complete = false`. The UI then shows the known subtotal as "₹X + unknown fees".
- Coupons are stored and displayed separately. They are subtracted only when `eligibility = VERIFIED`, which in practice means the adapter's API says so.
- Published fee policies (`delivery_fees` with `source=PUBLISHED_POLICY`) are applied only if an admin entered them with a source URL and an effective date. They are labelled "per published policy, not confirmed for your cart".

### 5.5 PIN codes (`services/pincode.py`)
- Format check: `^[1-9][0-9]{5}$`.
- Existence check against the seeded `pincode_directory`, which returns the district and state.
- Each adapter declares `location_capability ∈ {NONE, PINCODE, PRECISE_LOCATION, STORE}`. If the capability is `PRECISE_LOCATION` and only a PIN code is available, the status is `NEEDS_PRECISE_LOCATION` and no delivery claim is made.

---

## 6. Adapter interface (`integrations/base.py`)

```python
class MarketplaceAdapter(Protocol):
    code: MarketplaceCode
    capabilities: AdapterCapabilities   # search_by_gtin, search_by_text, location, fees, coupons
    async def status(self) -> AdapterStatus            # NOT_CONFIGURED | UNSUPPORTED | LIVE | DEGRADED | DEMO
    async def get_product(self, external_id: str) -> SourceProduct
    async def search(self, query: ProductQuery) -> list[Candidate]
    async def check_location(self, external_id: str, pincode: str) -> LocationResult
    async def get_offer(self, external_id: str, pincode: str | None) -> Offer   # price, mrp, fees, stock
```
- There is a typed error hierarchy: `AdapterNotConfigured`, `AdapterUnsupported`, `AdapterAuthError`, `AdapterRateLimited(retry_after)`, `AdapterTimeout`, `AdapterUpstreamError`. Only the timeout, rate-limited and upstream errors are retried.
- `registry.py` builds the adapters from settings. In demo mode every code maps to `MockAdapter(code)`. In live mode an adapter is reported as `LIVE` only after a successful health probe, which is recorded in `integration_health_logs`.
- Mock fixtures cover the scenarios the tests and the demo need:
  - an exact GTIN match
  - the same product at 1 kg vs 500 g (veto)
  - a pack of 2 vs a single pack (veto)
  - a colour variant
  - out of stock
  - not serviceable at the PIN code
  - a missing fee (UNKNOWN)
  - an adapter that times out
  - an adapter that returns a 500 error

---

## 7. Security

- **SSRF guard (`safe_http.py`):**
  - Resolves DNS itself and rejects loopback, private (RFC1918), link-local, CGNAT, multicast, reserved and IPv6 ULA/link-local addresses, plus `169.254.169.254` and `fd00:ec2::254`.
  - Connects to the IP it validated, which prevents DNS rebinding.
  - Allows at most 3 redirects, re-validating each hop against both the host allowlist and the IP checks.
  - 5 s timeout, a cap on response size, and `HEAD`/`GET` with `stream` only.
- **Auth:** the backend verifies Supabase JWTs against the project's JWKS (issuer, audience and expiry). Admin routes check `users.role == "admin"`.
- **Rate limits** are Redis token buckets, keyed by user, or by IP hash for anonymous users. Defaults are 10 comparisons per minute for anonymous users and 30 per minute for signed-in users. Responses return `429` with `Retry-After`.
- CORS uses an explicit origin allowlist. Responses carry security headers (HSTS, CSP on the frontend, `X-Content-Type-Options`). Request bodies have a size limit.
- SQL goes through the SQLAlchemy ORM with bound parameters only. React escapes output, `dangerouslySetInnerHTML` is never used, and product text and image URLs are sanitized (images use the `next/image` remotePatterns allowlist).
- Secrets live only in environment variables or a secrets manager. The frontend only ever sees `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` and `NEXT_PUBLIC_API_URL`.
- Logs are structured JSON (structlog) with request IDs, and PII and secrets are redacted. Admin actions, logins and credential-reference changes are written to the audit log.

---

## 8. API surface (`/api/v1`)

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/comparisons` | optional | 202 + id; idempotent within the cache TTL |
| GET | `/comparisons/{id}` | owner or anon token | results, per-marketplace status, data_mode |
| POST | `/comparisons/{id}/refresh` | optional | bypasses the cache |
| POST | `/comparisons/{id}/retry` | optional | `?marketplace=` re-runs failed adapters only |
| GET | `/products/{id}` | public | canonical product + variants |
| GET | `/products/{id}/price-history` | public | `?marketplace=&pincode=&range=30d` |
| GET | `/products/by-slug/{slug}` | public | used by SEO pages |
| GET | `/categories/{slug}/products` | public | paginated |
| GET | `/marketplaces` | public | list + capabilities + current status |
| GET | `/marketplaces/health` | public (summary) / admin (detail) | |
| POST | `/location/validate` | public | format + directory lookup |
| GET | `/search/history` | user | cursor pagination |
| GET/POST/DELETE | `/saved-products` | user | |
| GET/POST/PATCH/DELETE | `/alerts` | user | email delivery stubbed (logged only) |
| GET | `/me` · PATCH `/me` | user | profile, default PIN code |
| GET | `/admin/users`, `/admin/integrations`, `/admin/activity`, `/admin/errors`, `/admin/health` | admin | |

All errors use one format: `{"error": {"code", "message", "details", "request_id"}}`. List endpoints use cursor pagination (`?cursor=&limit=`). Swagger UI is served at `/docs` and ReDoc at `/redoc`.

---

## 9. Frontend and design system

- **Stack:** Next.js 15 App Router, TypeScript in strict mode, Tailwind v4, shadcn/ui (Radix), Lucide icons, TanStack Query for polling, react-hook-form + zod, Recharts for price history, `@supabase/ssr` for auth.
- **Visual language:**
  - Neutral surfaces (`zinc-50` page, white cards) and `zinc-900` text.
  - A single indigo accent (`indigo-600`) used only for primary actions and the "cheapest verified" highlight.
  - Rounded cards (`rounded-2xl`), 1 px borders plus a soft shadow.
  - Inter for UI text, tabular numerals for prices.
  - Motion is limited to 150–200 ms fades and skeleton shimmer, and respects `prefers-reduced-motion`.
- **Comparison dashboard:**
  - A source product header: image, brand, variant, size, PIN code, data-mode badge.
  - A summary strip: cheapest verified option and savings against the source marketplace.
  - A results table on desktop and stacked cards on mobile, with the full price breakdown in a popover per row.
  - Match badge with expandable reasons. Status chips: Verified / Unverified / Unavailable / Not configured / Failed, each with a retry button.
  - Filters (exact, probable, in stock, marketplace), sort by final price, refresh, and a data-source status panel.
- **No dead controls.** Any feature that is not wired up yet is hidden, not shown disabled. "View product" links only to the stored, validated marketplace URL, with `rel="noopener noreferrer nofollow sponsored"` where it is an affiliate link.

---

## 10. Phases, deliverables and tests

| Phase | Deliverables | Tests run at the end |
|---|---|---|
| **1. Setup** | git init, folder layout, docker-compose (pg, redis), backend skeleton with config/logging/errors/health, Alembic + all tables, marketplace seed, Next.js + Tailwind + shadcn + design tokens, `.env.example`, README skeleton | `pytest` (health, migration up/down), `npm run lint && typecheck` |
| **2. Homepage** | URL + PIN form with zod validation, `/location/validate`, inline errors, responsive layout | vitest form tests, API tests for PIN validation |
| **3. Extraction & normalization** | `url_parser`, `safe_http`, `normalization` | unit: every URL pattern, SSRF block list (localhost, 10/8, 169.254.169.254, IPv6, redirect to private), quantity parsing table (~40 cases) |
| **4. Adapters** | base protocol, registry, mock adapter + fixtures, Amazon/Flipkart shells (`NOT_CONFIGURED`), quick-commerce provider shells (`UNSUPPORTED`), Celery group/chord orchestration | adapter error mapping, timeout → FAILED result, partial results when 2 of 5 fail, retry/backoff (Celery eager + fake clock) |
| **5. Matching** | rule engine, RapidFuzz scorer, optional LLM review behind a flag | exact GTIN, brand veto, 500 g vs 1 kg veto, pack-of-2 veto, colour veto, probable vs unverified boundaries, LLM cannot promote to EXACT |
| **6. Location & pricing** | pincode directory seed, location capability handling, price service, fee policy table | price formula with unknown fees, unverified coupon not subtracted, Decimal rounding, NEEDS_PRECISE_LOCATION path |
| **7. Dashboard & history** | `/compare/[id]` full dashboard, polling, filters/sort/retry/refresh, price history chart, product + category SEO pages, sitemap | component tests, Playwright e2e in demo mode (paste → results → filter → retry) |
| **8. Auth, history, admin** | Supabase login, JWT verification, `/me`, search history, saved products, alerts (stored + evaluated by beat task; email stub), admin dashboard | authz tests (user can't read others' comparisons; non-admin 403), alert evaluation |
| **9. Hardening & deploy** | rate limits, security headers, audit log, Dockerfiles (multi-stage), Render blueprint (`render.yaml`), Vercel config, DEPLOYMENT.md, load sanity check | full suite, `pip-audit`, `npm audit`, coverage report |

Each phase is built and tested before the next one starts. I'll report actual test results at the end of every phase.

---

## 11. Decisions needed from you

1. **Supabase project.** Do you already have one? If not, Phase 8 can still be built, and locally it will run with a clearly labelled dev-auth mode (`AUTH_MODE=dev`, refused when `ENV=production`) until you add the Supabase URL and keys.
2. **Marketplace access.** Do you have, or are you applying for, Amazon Associates / Creators API access or a Flipkart Affiliate account? This changes nothing in the build order. It only decides whether a live adapter gets tested against real credentials.
3. **Quick-commerce data provider.** Blinkit, Zepto and BigBasket stay `UNSUPPORTED` outside demo mode until you choose a licensed provider. I will not wire up unofficial endpoints.
4. **LLM review.** It is off by default. If you want it, it would use the Claude API with your `ANTHROPIC_API_KEY` set on the server.

---

## 12. Added during build: card / bank offers (Phase 4)

- Each offer may carry `card_offers` (bank, credit/debit, network, % or flat, cap, minimum
  order, EMI-only, terms) when the marketplace's authorized channel provides them.
- Evaluated on the order value (item price minus verified discounts): cap and minimum order
  applied. The best offer is the largest **regular** one; EMI-only offers win only if nothing
  else applies.
- Never part of the final price: eligibility depends on the shopper's card. Shown as "price
  with best card" per marketplace and "best with a card offer" overall, with delivery caveats.
- Phase 8: users can save which banks' cards they hold, so "best" uses only their cards.
- Real card data depends on what each approved API exposes; until verified, only demo data
  (fictional "Demo Bank" offers) contains card offers.
