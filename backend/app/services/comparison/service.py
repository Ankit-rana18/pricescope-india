"""Run a comparison end to end and keep it available while it runs and afterwards.

Flow: read the pasted product from its own marketplace -> record the comparison -> fetch
all five marketplaces concurrently (threads or Celery) -> match, price and rank each result
as it arrives (visible immediately through GET) -> store everything in one batch per table.

Only this process writes to storage (workers only do marketplace I/O), which keeps the
Google Sheets backend safe. Storage writes per comparison: about five API calls.
"""

import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from http import HTTPStatus
from typing import Any

import structlog
from pricescope_integrations.base import AdapterError, ListingNotFound, MarketplaceAdapter
from pricescope_integrations.models import (
    AdapterState,
    DataSource,
    Listing,
    Marketplace,
    ProductQuery,
)
from pricescope_integrations.runner import RetryPolicy, call_with_retry

from app.core.errors import AppError, NotFoundError
from app.models.enums import ComparisonStatus, DataMode, MarketplaceCode
from app.schemas.comparison import (
    CandidateView,
    CardOfferView,
    ChargeView,
    ComparisonView,
    CouponView,
    PriceView,
    ResultView,
    SummaryView,
)
from app.services.comparison.evaluate import evaluate, listing_view, name_of, rank_and_summarize
from app.services.comparison.executors import FetchExecutor, FetchJob
from app.services.url_parser import ParsedProductUrl
from app.storage.base import TableStore
from app.storage.errors import RowNotFound

log = structlog.get_logger(__name__)

FINAL = {ComparisonStatus.COMPLETE, ComparisonStatus.PARTIAL, ComparisonStatus.FAILED}
CHARGES = ("delivery_fee", "handling_fee", "platform_fee", "other_fees")


class SourceNotFound(AppError):
    status_code = HTTPStatus.NOT_FOUND
    code = "source_not_found"


class SourceUnavailable(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "source_unavailable"


class ComparisonService:
    def __init__(
        self,
        store: TableStore,
        adapters: dict[Marketplace, MarketplaceAdapter],
        executor: FetchExecutor,
        *,
        data_mode: DataMode,
        reuse_seconds: float = 600,
        max_parallel: int = 4,
        keep_in_memory: int = 200,
        source_policy: RetryPolicy | None = None,
    ) -> None:
        self._store = store
        self._adapters = adapters
        self._executor = executor
        self._data_mode = data_mode
        self._reuse_seconds = reuse_seconds
        self._keep = keep_in_memory
        self._source_policy = source_policy or RetryPolicy(deadline_seconds=8)
        self._lock = threading.RLock()
        self._views: OrderedDict[str, ComparisonView] = OrderedDict()
        self._futures: dict[str, Future[None]] = {}
        self._reuse: dict[tuple[str, str, str], tuple[str, float]] = {}
        self._marketplace_ids: dict[MarketplaceCode, Any] = {}
        self._pool = ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix="compare")

    # ------------------------------------------------------------------ public API

    def start(self, parsed: ParsedProductUrl, pincode: str) -> ComparisonView:
        reuse_key = (parsed.marketplace.value, parsed.external_id.casefold(), pincode)
        with self._lock:
            hit = self._reuse.get(reuse_key)
            if hit and hit[1] > time.monotonic():
                try:
                    view = self.get(hit[0])
                except NotFoundError:
                    view = None
                if view and view.status in FINAL:
                    view.reused = True
                    return view

        source = self._load_source(parsed)
        row = self._store.insert(
            "comparisons",
            {
                "source_url": parsed.canonical_url,
                "pincode": pincode,
                "status": ComparisonStatus.RUNNING,
                "data_mode": self._data_mode,
            },
        )
        comparison_id = str(row["id"])
        view = ComparisonView(
            id=comparison_id,
            status=ComparisonStatus.RUNNING,
            data_mode=self._data_mode,
            pincode=pincode,
            source_url=parsed.canonical_url,
            created_at=row["created_at"],
            source=listing_view(source),
            results=[
                ResultView(
                    marketplace=MarketplaceCode(m.value),
                    marketplace_name=name_of(m.value),
                    status="PENDING",
                )
                for m in Marketplace
            ],
            summary=SummaryView(),
        )
        with self._lock:
            self._remember(view)
            self._futures[comparison_id] = self._pool.submit(
                self._run, comparison_id, source, pincode, reuse_key
            )
        return view.model_copy(deep=True)

    def get(self, comparison_id: str) -> ComparisonView:
        with self._lock:
            if comparison_id in self._views:
                self._views.move_to_end(comparison_id)
                return self._views[comparison_id].model_copy(deep=True)
        view = self._rebuild(comparison_id)
        with self._lock:
            self._remember(view)
        return view.model_copy(deep=True)

    def wait(self, comparison_id: str, timeout: float = 30) -> ComparisonView:
        fut = self._futures.get(comparison_id)
        if fut is not None:
            fut.result(timeout=timeout)
        return self.get(comparison_id)

    def statuses(self) -> list[Any]:
        return [self._adapters[m].status() for m in Marketplace]

    # ------------------------------------------------------------------ running

    def _load_source(self, parsed: ParsedProductUrl) -> Listing:
        marketplace = Marketplace(parsed.marketplace.value)
        adapter = self._adapters[marketplace]
        status = adapter.status()
        name = name_of(marketplace.value)
        if status.state in (AdapterState.NOT_CONFIGURED, AdapterState.UNSUPPORTED):
            raise SourceUnavailable(
                f"{name} isn't connected yet, so the product's details can't be read. "
                f"{status.reason}",
                details={"marketplace": marketplace.value, "state": status.state.value},
            )
        try:
            return call_with_retry(
                lambda: adapter.get_listing(parsed.external_id), self._source_policy
            )
        except ListingNotFound:
            hint = (
                " In demo mode only the sample products can be compared."
                if self._data_mode is DataMode.DEMO
                else ""
            )
            raise SourceNotFound(
                f"We couldn't find this product on {name}.{hint}",
                details={"marketplace": marketplace.value, "external_id": parsed.external_id},
            ) from None
        except AdapterError as exc:
            raise SourceUnavailable(
                f"{name} didn't respond, so the product's details couldn't be read. "
                "Try again shortly.",
                details={"marketplace": marketplace.value, "reason": exc.code},
            ) from None

    def _run(
        self, comparison_id: str, source: Listing, pincode: str, reuse_key: tuple[str, str, str]
    ) -> None:
        query = ProductQuery(
            title=source.title,
            brand=source.brand,
            model=source.model,
            gtin=source.gtin,
            attributes=source.attributes,
        )
        jobs = [FetchJob(m, query, pincode, source) for m in Marketplace]
        try:
            for fetch in self._executor.run(jobs):
                result = evaluate(source, fetch)
                with self._lock:
                    view = self._views[comparison_id]
                    view.results = [
                        result if r.marketplace == result.marketplace else r for r in view.results
                    ]
                    view.results, view.summary = rank_and_summarize(view.results)
        except Exception:
            log.exception("comparison_run_failed", comparison_id=comparison_id)

        with self._lock:
            view = self._views[comparison_id]
            for r in view.results:
                if r.status == "PENDING":
                    r.status = "FAILED"
                    r.status_reason = "No result was received"
            view.results, view.summary = rank_and_summarize(view.results)
            failed = sum(1 for r in view.results if r.status == "FAILED")
            view.status = (
                ComparisonStatus.FAILED
                if failed == len(view.results)
                else ComparisonStatus.PARTIAL
                if failed
                else ComparisonStatus.COMPLETE
            )
            view.completed_at = datetime.now(UTC)
            snapshot = view.model_copy(deep=True)

        try:
            self._persist(snapshot, source)
        except Exception:
            log.exception("comparison_persist_failed", comparison_id=comparison_id)
            with self._lock:
                self._views[
                    comparison_id
                ].storage_note = (
                    "These results couldn't be saved, so they'll be gone after a restart."
                )
        with self._lock:
            self._reuse[reuse_key] = (comparison_id, time.monotonic() + self._reuse_seconds)
            self._futures.pop(comparison_id, None)

    def _remember(self, view: ComparisonView) -> None:
        self._views[view.id] = view
        self._views.move_to_end(view.id)
        while len(self._views) > self._keep:
            oldest, old_view = next(iter(self._views.items()))
            if old_view.status not in FINAL:
                break  # never evict a running comparison
            self._views.pop(oldest)

    # ------------------------------------------------------------------ storage

    def _marketplace_id(self, code: MarketplaceCode) -> Any:
        if not self._marketplace_ids:
            self._marketplace_ids = {
                MarketplaceCode(r["code"]): r["id"] for r in self._store.find("marketplaces")
            }
        return self._marketplace_ids[code]

    def _listing_ids(self, listings: list[Listing]) -> dict[tuple[str, str], Any]:
        ids: dict[tuple[str, str], Any] = {}
        new_rows = []
        for lst in listings:
            key = (lst.marketplace.value, lst.external_id)
            if key in ids:
                continue
            mid = self._marketplace_id(MarketplaceCode(lst.marketplace.value))
            found = self._store.find(
                "marketplace_products", {"marketplace_id": mid, "external_id": lst.external_id}
            )
            if found:
                ids[key] = found[0]["id"]
                continue
            row_id = uuid.uuid4()
            ids[key] = row_id
            new_rows.append(
                {
                    "id": row_id,
                    "marketplace_id": mid,
                    "external_id": lst.external_id,
                    "url": lst.url,
                    "title_raw": lst.title,
                    "image_url": lst.image_url,
                    "attributes": {
                        "brand": lst.brand,
                        "model": lst.model,
                        "gtin": lst.gtin,
                        "data_source": lst.data_source.value,
                        "extra": lst.attributes,
                    },
                    "last_seen_at": datetime.now(UTC),
                }
            )
        self._store.insert_many("marketplace_products", new_rows)
        return ids

    def _persist(self, view: ComparisonView, source: Listing) -> None:
        data_source = DataSource(self._data_mode.value)
        listings = [source] + [
            Listing(
                marketplace=Marketplace(r.listing.marketplace.value),
                external_id=r.listing.external_id,
                title=r.listing.title,
                url=r.listing.url,
                image_url=r.listing.image_url,
                brand=r.listing.brand,
                model=r.listing.model,
                gtin=r.listing.gtin,
                data_source=data_source,
            )
            for r in view.results
            if r.listing is not None
        ]
        ids = self._listing_ids(listings)
        now = datetime.now(UTC)
        result_rows, history_rows = [], []
        for r in view.results:
            listing_id = (
                ids.get((r.listing.marketplace.value, r.listing.external_id)) if r.listing else None
            )
            result_rows.append(self._result_row(view.id, r, listing_id, now))
            if listing_id and r.price and r.price.item_price is not None:
                history_rows.append(
                    {
                        "marketplace_product_id": listing_id,
                        "pincode": view.pincode,
                        "item_price": r.price.item_price,
                        "mrp": r.price.mrp,
                        "final_price": r.price.final_price,
                        "final_price_complete": r.price.final_price_complete,
                        "data_mode": self._data_mode,
                        "observed_at": r.checked_at or now,
                    }
                )
        self._store.insert_many("comparison_results", result_rows)
        self._store.insert_many("price_history", history_rows)
        self._store.update(
            "comparisons",
            view.id,
            {
                "status": view.status,
                "completed_at": view.completed_at,
                "source_marketplace_product_id": ids[
                    (source.marketplace.value, source.external_id)
                ],
            },
        )

    def _result_row(
        self, comparison_id: str, r: ResultView, listing_id: Any, now: datetime
    ) -> dict[str, Any]:
        p = r.price
        row: dict[str, Any] = {
            "comparison_id": comparison_id,
            "marketplace_id": self._marketplace_id(r.marketplace),
            "marketplace_product_id": listing_id,
            "status": r.status,
            "match_class": r.match_class,
            "match_score": r.match_score,
            "match_reasons": r.match_reasons,
            "availability": r.availability,
            "location_verification": r.location_verification,
            "eta_text": r.eta_text,
            "error_code": None if r.status == "OK" else r.status.lower(),
            "error_message": r.status_reason,
            "card_offers": [c.model_dump(mode="json") for c in r.card_offers],
            "best_card_discount": r.best_card.discount if r.best_card else None,
            "price_after_best_card": r.price_after_best_card,
            "other_candidates": [c.model_dump(mode="json") for c in r.other_candidates],
            "attempts": r.attempts,
            "latency_ms": r.latency_ms,
            "checked_at": r.checked_at or now,
        }
        if p is not None:
            charges = {k: getattr(p, k) for k in CHARGES}
            row.update(
                {
                    "mrp": p.mrp,
                    "item_price": p.item_price,
                    "verified_discount": p.verified_discount,
                    "coupons": [c.model_dump(mode="json") for c in p.coupons],
                    "assumptions": p.assumptions,
                    "final_price": p.final_price,
                    "final_price_complete": p.final_price_complete,
                    "charge_notes": {k: c.note for k, c in charges.items() if c.note},
                    **{k: c.amount for k, c in charges.items()},
                    **{f"{k}_status": c.status for k, c in charges.items()},
                }
            )
        return row

    def _rebuild(self, comparison_id: str) -> ComparisonView:
        try:
            cmp = self._store.get("comparisons", comparison_id)
        except RowNotFound:
            raise NotFoundError("Comparison not found.") from None
        source_id = cmp.get("source_marketplace_product_id")
        if source_id is None:
            raise NotFoundError("This comparison didn't finish, so it has no saved results.")
        codes = {v: k for k, v in self._marketplace_id_map().items()}
        source_row = self._store.get("marketplace_products", source_id)
        results = []
        for row in self._store.find("comparison_results", {"comparison_id": cmp["id"]}):
            listing_row = (
                self._store.get("marketplace_products", row["marketplace_product_id"])
                if row.get("marketplace_product_id")
                else None
            )
            results.append(self._result_from_row(row, codes[row["marketplace_id"]], listing_row))
        ranked, summary = rank_and_summarize(results)
        status = ComparisonStatus(cmp["status"])
        return ComparisonView(
            id=str(cmp["id"]),
            status=status,
            data_mode=DataMode(cmp["data_mode"]),
            pincode=cmp["pincode"],
            source_url=cmp["source_url"],
            created_at=cmp["created_at"],
            completed_at=cmp.get("completed_at"),
            source=listing_view(
                self._listing_from_row(source_row, codes[source_row["marketplace_id"]])
            ),
            results=ranked,
            summary=summary,
        )

    def _marketplace_id_map(self) -> dict[MarketplaceCode, Any]:
        self._marketplace_id(MarketplaceCode.AMAZON_IN)
        return self._marketplace_ids

    def _listing_from_row(self, row: dict[str, Any], code: MarketplaceCode) -> Listing:
        attrs = row.get("attributes") or {}
        return Listing(
            marketplace=Marketplace(code.value),
            external_id=row["external_id"],
            title=row["title_raw"],
            url=row.get("url"),
            image_url=row.get("image_url"),
            brand=attrs.get("brand"),
            model=attrs.get("model"),
            gtin=attrs.get("gtin"),
            attributes=attrs.get("extra") or {},
            data_source=DataSource(attrs.get("data_source", "DEMO")),
        )

    def _result_from_row(
        self, row: dict[str, Any], code: MarketplaceCode, listing_row: dict[str, Any] | None
    ) -> ResultView:
        notes = row.get("charge_notes") or {}
        price = None
        if row.get("item_price") is not None or row.get("final_price") is not None:
            price = PriceView(
                item_price=row.get("item_price"),
                mrp=row.get("mrp"),
                verified_discount=row.get("verified_discount") or Decimal("0.00"),
                coupons=[CouponView(**c) for c in row.get("coupons") or []],
                final_price=row.get("final_price"),
                final_price_complete=bool(row.get("final_price_complete")),
                assumptions=row.get("assumptions") or [],
                **{
                    k: ChargeView(status=row[f"{k}_status"], amount=row.get(k), note=notes.get(k))
                    for k in CHARGES
                },
            )
        cards = [CardOfferView(**c) for c in row.get("card_offers") or []]
        best = cards[0] if cards and cards[0].discount else None
        return ResultView(
            marketplace=code,
            marketplace_name=name_of(code),
            status=row["status"],
            status_reason=row.get("error_message"),
            listing=listing_view(self._listing_from_row(listing_row, code))
            if listing_row
            else None,
            match_class=row.get("match_class"),
            match_score=row.get("match_score"),
            match_reasons=row.get("match_reasons") or [],
            price=price,
            card_offers=cards,
            best_card=best,
            price_after_best_card=row.get("price_after_best_card"),
            availability=row.get("availability"),
            location_verification=row.get("location_verification"),
            eta_text=row.get("eta_text"),
            other_candidates=[CandidateView(**c) for c in row.get("other_candidates") or []],
            is_source=(row.get("match_reasons") or []) == ["the product you pasted"],
            attempts=row.get("attempts"),
            latency_ms=row.get("latency_ms"),
            checked_at=row.get("checked_at"),
        )


ServiceFactory = Callable[[], ComparisonService]
