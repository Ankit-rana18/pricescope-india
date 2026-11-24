# Storage: Google Sheets (interim) and PostgreSQL

PriceScope stores its data through one interface (`app/storage/base.py: TableStore`) with two
interchangeable backends:

| `PRICESCOPE_STORAGE_BACKEND` | Where data lives | Status |
|---|---|---|
| `sheets` (default) | One Google spreadsheet, one tab per table | Interim primary store |
| `postgres` | PostgreSQL 16 (Alembic migrations) | Ready; switch back any time |

The SQLAlchemy models in `backend/app/models/` are the single source of truth for both. The tab
names, column headers, types, defaults, unique keys, foreign keys and CHECK rules all come from
those models. Both backends run the same validation (`app/storage/schema.py`, `rules.py`), and
`tests/integration/test_storage_contract.py` runs the same scenarios against both to prove they
behave the same.

## Set up Google Sheets

You need to do these steps yourself in Google Cloud and Google Sheets. The app never creates
accounts or keys.

1. **Create a Google Cloud project** (or reuse one) at <https://console.cloud.google.com/>.
2. **Enable the Google Sheets API** for it (APIs & Services → Library → "Google Sheets API").
3. **Create a service account** (IAM & Admin → Service Accounts). It needs no project roles.
4. **Create a JSON key** for that service account (Keys → Add key → JSON) and download it.
   Treat this file as a password.
5. **Create an empty spreadsheet** in Google Sheets, then **Share** it with the service
   account's email (`…@….iam.gserviceaccount.com`) as **Editor**.
6. **Configure `.env`**:
   - `PRICESCOPE_GOOGLE_SHEETS_SPREADSHEET_ID`: the id in the sheet URL
     (`https://docs.google.com/spreadsheets/d/<ID>/edit`).
   - Local dev: save the key as `secrets/service-account.json` (git-ignored) and set
     `PRICESCOPE_GOOGLE_SERVICE_ACCOUNT_FILE=../secrets/service-account.json`. The path is
     relative to `backend/`.
   - Docker or hosting: put the key JSON on one line in `PRICESCOPE_GOOGLE_SERVICE_ACCOUNT_JSON`
     instead (a secret env var on Render or AWS).
7. **Create the tabs and seed data**:

   ```powershell
   cd backend; uv run python -m app.storage.bootstrap
   ```

   This creates all 17 tabs with frozen header rows and adds the five marketplaces. Every
   marketplace capability starts as `unverified`. It is safe to re-run: it only adds what is
   missing and never deletes or rewrites data.
8. Check `http://localhost:8000/api/v1/health/ready`: it should show `"storage": "ok"`.

The app asks Google only for the `spreadsheets` scope. It has no Drive access and can only reach
spreadsheets that have been explicitly shared with the service account.

## How data is stored

- **One row per record.** Row 1 holds the column headers. Columns are matched **by header
  name**, so reordering columns in the sheet UI is safe.
- **Text, written RAW.** Values are never interpreted as formulas, so a product title like
  `=IMPORTXML(…)` is stored as plain text.
- **Exact formats:**
  - Money is stored as exact decimal text (`"99.50"`), never a float.
  - Timestamps are ISO 8601 UTC.
  - Booleans are `TRUE` / `FALSE`.
  - JSON and arrays are compact JSON.
  - An empty cell means NULL. Unknown fees stay empty with a `*_status` of `UNKNOWN`, never 0.
- **Rules a database would normally enforce are enforced by the app:**
  - types, NOT NULL, enum values and text length
  - every CHECK rule (PIN format, secret references only, a complete price needs a value, …)
  - primary and unique keys (email is case-insensitive)
  - foreign keys
  - `ON DELETE` actions. RESTRICT is checked across the whole cascade before anything is
    deleted, so a refused delete changes nothing.
- **Hand edits:**
  - Extra columns you add by hand are kept when rows are updated.
  - A cell you break by hand (e.g. `pack_count = "two"`) makes that row skipped in lists, and
    the row is reported with its tab, row and column when fetched directly.

## Limits while Sheets is the primary store

| Limit | Effect | Mitigation |
|---|---|---|
| No transactions; locking is per process | Two processes writing at once can race on unique-key checks | Run **one API process** with Sheets. Celery workers (Phase 4) should write through the API or one designated writer |
| Google quota: about 60 read requests per minute per user | Heavy traffic gets HTTP 429 | gspread's backoff client retries automatically. Tabs are cached (`PRICESCOPE_SHEETS_CACHE_TTL_SECONDS`, default 10 s), and this process's own writes invalidate the cache immediately |
| Each read downloads a whole tab | Slower as tabs grow (thousands of rows) | Move `price_history` and the large lookup tables to PostgreSQL first |
| 10 million cells per spreadsheet | The full India Post PIN directory (about 165k rows) would be slow | Phase 6 will load the PIN directory from a bundled data file, not from Sheets |
| Other processes see writes up to the cache TTL late | Short staleness | Uniqueness checks always re-read the tab being written |

## Switching to PostgreSQL

```powershell
docker compose up -d postgres
```

```powershell
cd backend; uv run alembic upgrade head
```

Then set `PRICESCOPE_STORAGE_BACKEND=postgres`. Copying existing Sheets data into PostgreSQL
is a one-off export script (not written yet): read each tab through `SheetsTableStore` and
insert it through `SqlTableStore`, parents before children.
