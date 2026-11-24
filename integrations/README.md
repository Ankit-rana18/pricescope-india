# pricescope-integrations

Marketplace adapters, independent of the backend app (it imports nothing from `backend/`).

| Module | Purpose |
|---|---|
| `models.py` | JSON-serialisable data exchanged with adapters (listings, offers, fees, card offers) |
| `base.py` | `MarketplaceAdapter` protocol and error hierarchy (retryable vs not) |
| `official.py` | Amazon Creators API / Flipkart Affiliate shells (`NOT_CONFIGURED`), licensed-provider shells for Blinkit / Zepto / BigBasket (`UNSUPPORTED`) |
| `demo/` | Fictional catalog + adapter used only in demo mode; every value is labelled `DEMO` |
| `registry.py` | Builds the adapter set: all-demo or all-official, never mixed |
| `runner.py` | `fetch_marketplace`: retries with backoff + jitter, deadline, never raises |

No adapter is reported `LIVE` until its credentials are present **and** a real call to the
official API has been verified. No unofficial endpoints, scraping or access-control bypass.
