# Database schema notes

The source of truth is the SQLAlchemy models in `backend/app/models/` and the Alembic migrations in
`backend/alembic/versions/`. This file explains the conventions.

## Conventions

- Primary keys are `uuid` from `gen_random_uuid()` (pgcrypto). `users.id` has no default, because
  it equals the Supabase auth user id.
- Timestamps are `timestamptz`: `created_at` and `updated_at` on mutable tables, and
  `observed_at`, `checked_at` or `occurred_at` on append-only logs.
- Money is `numeric(12,2)` in INR. It is never stored as a float.
- **Unknown is never zero.** Every fee column in `comparison_results` is paired with a
  `*_status` column (`KNOWN` / `UNKNOWN` / `NOT_APPLICABLE`). An unknown amount is stored as
  `NULL`. `final_price_complete = true` requires a non-null `final_price` (CHECK).
- Enums are stored as `VARCHAR` plus a `CHECK` constraint rather than native Postgres enums, so
  adding a value is a simple migration.
- PIN codes are checked by `CHECK (pincode ~ '^[1-9][0-9]{5}$')` on every table that stores one.
- Constraint names are deterministic (see `NAMING_CONVENTION` in `models/base.py`).

## Tables

| Group | Tables |
|---|---|
| Catalog | `marketplaces`, `products`, `product_variants`, `product_identifiers`, `marketplace_products` |
| Comparison | `comparisons`, `comparison_results`, `price_history`, `location_checks`, `delivery_fees` |
| Users | `users`, `saved_products`, `price_alerts`, `audit_logs` |
| Integrations | `integration_credentials` (secret **references** only), `integration_health_logs` |
| Reference data | `pincode_directory` (India Post open data, loaded in Phase 6) |

## Seed data

Migration `a1c3e5f70002` seeds the five marketplaces. Every capability starts as `"unverified"`
and is updated only by a successful adapter health probe against real, authorized credentials.
