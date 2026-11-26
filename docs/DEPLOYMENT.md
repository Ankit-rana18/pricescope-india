# Deploying PriceScope India

Target setup:

| Part | Where | Config |
|---|---|---|
| API (FastAPI) | Render web service, Docker, Singapore region | `render.yaml` |
| Database | Render Postgres | `render.yaml` |
| Frontend (Next.js) | Vercel, Mumbai functions region (`bom1`) | `frontend/vercel.json` |
| Sign-in | Supabase Auth (email links) | dashboard settings below |

Production uses **Postgres**, not Google Sheets. Sheets is fine for local work, but each
comparison makes 5 Sheet appends (10–20 s) and Google's API quotas would cap traffic.

> The deployment still runs in **demo mode**: Amazon and Flipkart need approved API access,
> and Blinkit, Zepto and BigBasket need a licensed data provider (see the implementation
> plan, §11). Every demo price is labelled as sample data in the API and the UI.

## What you need

- A GitHub repo with this code (already: `Ankit-rana18/pricescope-india`).
- Accounts on Render, Vercel and Supabase. Free tiers work for a first deploy.
- A Supabase project. The API refuses to start in production without one (dev sign-in is
  blocked there by design).

## 1. Supabase

1. Create a project. Copy from **Project Settings → API**: the **Project URL**
   (`https://<ref>.supabase.co`) and the **anon public** key.
2. **Authentication → Sign In / Providers**: keep **Email** enabled.
3. **Authentication → URL Configuration**: set **Site URL** to your Vercel URL and add
   `https://<your-vercel-domain>/auth/callback` to **Redirect URLs** (add the preview
   domain too if you want sign-in on preview deploys).

The API verifies tokens against the project's public signing keys (JWKS), so no secret is
needed. Only projects still on the legacy shared secret need `PRICESCOPE_SUPABASE_JWT_SECRET`.

## 2. API and database on Render

1. Render → **New → Blueprint** → pick the repo. Render reads `render.yaml` and creates
   `pricescope-api` and `pricescope-db`.
2. It asks for the values marked `sync: false`:
   - `PRICESCOPE_SUPABASE_URL`: the Supabase Project URL.
   - `PRICESCOPE_CORS_ORIGINS`: your Vercel URL, e.g. `https://pricescope.vercel.app`
     (comma-separate several; wildcards are refused in production). You can put a
     placeholder now and fix it after step 3.
   - `PRICESCOPE_ADMIN_EMAILS`: your email. It becomes admin on first sign-in.
3. Deploy. On start the container runs `alembic upgrade head`, then the API. Check
   `https://<api>.onrender.com/api/v1/health/ready`: it should show `"storage": "ok"`.
   Marketplace reference rows come from a migration, and demo products come from the
   demo adapter, so there is no separate seed step.

Free-plan limits (Render docs, Nov 2026): the web service sleeps after 15 idle minutes and
takes about a minute to wake; free Postgres has 1 GB, no backups and **expires after 30
days**. Switch both to paid plans in the dashboard before real users depend on it.

## 3. Frontend on Vercel

1. Vercel → **Add New → Project** → import the repo.
2. **Root Directory**: `frontend`. Framework is detected as Next.js; `frontend/vercel.json`
   pins the install/build commands and the Mumbai region.
3. **Environment Variables** (Production, and Preview if you use it):
   - `NEXT_PUBLIC_API_URL` = `https://<api>.onrender.com`
   - `NEXT_PUBLIC_SITE_URL` = your Vercel URL
   - `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` from step 1.

   These are baked in at build time, so redeploy after changing them. The Content Security
   Policy only allows calls to these two origins.
4. Deploy, then put the final Vercel URL into `PRICESCOPE_CORS_ORIGINS` on Render and into
   Supabase's Site URL / Redirect URLs.

## 4. After the first deploy

- Sign in with your admin email and open **Admin dashboard**.
- **Client IPs (rate limits).** Anonymous visitors are rate-limited by IP. Behind Render's
  proxy the API only sees the proxy's address unless it trusts `X-Forwarded-For`, and how
  many proxies append to that header isn't something we could confirm from Render's docs.
  So `PRICESCOPE_TRUSTED_PROXY_HOPS` starts at `0` (header ignored: safe, but every
  anonymous visitor then shares one limit). To set it properly, open the admin dashboard's
  **Your connection** panel (or `GET /api/v1/admin/request-info`). Count entries in
  *X-Forwarded-For* from the right until you reach your own public IP; that count is the
  value to set. Recheck the panel: *client IP used* should now be your IP.
- Signed-in users are always limited by account, so they are unaffected by this.

## Settings reference (production)

| Variable | Value | Notes |
|---|---|---|
| `PRICESCOPE_ENV` | `production` | turns on HSTS and the production guards |
| `PRICESCOPE_AUTH_MODE` | `supabase` | `dev` is refused in production |
| `PRICESCOPE_STORAGE_BACKEND` | `postgres` | `postgres://` URLs from hosts are accepted |
| `PRICESCOPE_RATE_LIMIT_BACKEND` | `memory` | use `redis` + `PRICESCOPE_REDIS_URL` with more than one instance |
| `PRICESCOPE_RATE_LIMIT_SALT` | random | keeps hashed-IP keys stable across restarts |
| `PRICESCOPE_RATE_LIMIT_*` | per-minute limits | compare 10 anon / 30 user; lookup 30 / 60; writes 60 |
| `PRICESCOPE_MAX_BODY_BYTES` | `65536` | larger request bodies get 413 |
| `PRICESCOPE_TASK_EXECUTOR` | `threads` | `celery` needs Redis and a worker service (paid on Render) |

## Running the production images locally

```powershell
docker compose build api frontend
```

```powershell
docker compose up -d
```

`docker-compose.yml` builds the same `backend/Dockerfile` (non-root user, no dev
dependencies) and `frontend/Dockerfile` (Next.js standalone output) used above.
