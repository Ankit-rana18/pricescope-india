"""Accounts, ownership, history, saved products, alerts, card personalisation, admin."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pricescope_integrations.registry import IntegrationConfig, build_adapters
from pricescope_integrations.runner import RetryPolicy
from support.fake_sheets import FakeSheetClient

from app.api.v1.comparisons import get_comparison_service
from app.api.v1.lookup import get_pincode_directory
from app.api.v1.products import get_catalog
from app.core.auth import DevVerifier, UserDirectory, get_user_directory, get_verifier
from app.core.config import Environment, Settings
from app.main import create_app
from app.models.enums import DataMode
from app.services.catalog import CatalogService
from app.services.comparison.executors import ThreadFetchExecutor
from app.services.comparison.service import ComparisonService
from app.services.pincode import PincodeDirectory
from app.storage.bootstrap import bootstrap
from app.storage.sheets.store import SheetsTableStore

FAST = IntegrationConfig(demo_latency_seconds=(0, 0), demo_timeout_seconds=0.05)
POLICY = RetryPolicy(base_delay_seconds=0.001, max_delay_seconds=0.01)
PHONE = "https://www.amazon.in/dp/DEMO000003"
SALT = "https://www.amazon.in/dp/DEMO000001"
ADMIN = {"Authorization": "Bearer dev:ops@example.in"}
ASHA = {"Authorization": "Bearer dev:asha@example.in"}
RAVI = {"Authorization": "Bearer dev:ravi@example.in"}


class Env:
    def __init__(self) -> None:
        self.sheets = FakeSheetClient()
        bootstrap(self.sheets)
        self.store = SheetsTableStore(self.sheets)
        adapters = build_adapters(FAST)
        self.service = ComparisonService(
            self.store,
            adapters,
            ThreadFetchExecutor(adapters, policy=POLICY),
            data_mode=DataMode.DEMO,
        )
        directory = UserDirectory(self.store, ["ops@example.in"])
        app = create_app(Settings(env=Environment.TEST, log_level="WARNING"))
        app.dependency_overrides[get_comparison_service] = lambda: self.service
        app.dependency_overrides[get_catalog] = lambda: CatalogService(self.store)
        app.dependency_overrides[get_pincode_directory] = lambda: PincodeDirectory()
        app.dependency_overrides[get_verifier] = lambda: DevVerifier()
        app.dependency_overrides[get_user_directory] = lambda: directory
        self.c = TestClient(app)

    def compare(
        self, url: str, headers: dict[str, str] | None = None, pin: str = "560001"
    ) -> dict[str, Any]:
        r = self.c.post("/api/v1/comparisons", json={"url": url, "pincode": pin}, headers=headers)
        assert r.status_code in (200, 202), r.text
        self.service.wait(r.json()["id"])
        return self.c.get(f"/api/v1/comparisons/{r.json()['id']}", headers=headers).json()


@pytest.fixture
def env() -> Iterator[Env]:
    e = Env()
    with e.c:
        yield e


# ------------------------------------------------------------------ auth basics


def test_signed_out_can_still_compare_and_me_needs_sign_in(env: Env) -> None:
    view = env.compare(SALT)
    assert view["status"] == "COMPLETE"
    assert env.c.get("/api/v1/me").status_code == 401


def test_bad_token_is_an_error_not_anonymous(env: Env) -> None:
    r = env.c.get("/api/v1/comparisons/x", headers={"Authorization": "Bearer dev:nope"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_first_sign_in_creates_user_with_role_from_server_config(env: Env) -> None:
    me = env.c.get("/api/v1/me", headers=ASHA).json()
    assert me["email"] == "asha@example.in" and me["role"] == "user"
    assert env.c.get("/api/v1/me", headers=ADMIN).json()["role"] == "admin"
    assert len(env.store.find("users")) == 2


def test_update_profile_and_cards(env: Env) -> None:
    r = env.c.patch(
        "/api/v1/me",
        headers=ASHA,
        json={
            "display_name": "  Asha  ",
            "default_pincode": "560 001",
            "preferences": {
                "card_banks": ["Demo Bank C", "demo bank c", " "],
                "card_types": ["CREDIT"],
            },
        },
    ).json()
    assert r["display_name"] == "Asha"
    assert r["default_pincode"] == "560001"
    assert r["preferences"] == {"card_banks": ["Demo Bank C"], "card_types": ["CREDIT"]}
    bad = env.c.patch("/api/v1/me", headers=ASHA, json={"default_pincode": "012345"})
    assert bad.status_code == 409


# ------------------------------------------------------------------ ownership


def test_signed_in_comparisons_are_private(env: Env) -> None:
    mine = env.compare(SALT, ASHA)
    cid = mine["id"]
    assert "owner_id" not in mine  # never sent to clients
    assert env.c.get(f"/api/v1/comparisons/{cid}", headers=ASHA).status_code == 200
    assert env.c.get(f"/api/v1/comparisons/{cid}", headers=RAVI).status_code == 404
    assert env.c.get(f"/api/v1/comparisons/{cid}").status_code == 404
    assert env.c.get(f"/api/v1/comparisons/{cid}", headers=ADMIN).status_code == 200
    assert env.c.post(f"/api/v1/comparisons/{cid}/refresh", headers=RAVI).status_code == 404
    assert env.c.post(f"/api/v1/comparisons/{cid}/retry", headers=RAVI).status_code == 404


def test_reuse_never_hands_out_someone_elses_comparison(env: Env) -> None:
    a = env.compare(SALT, ASHA)
    r = env.c.post("/api/v1/comparisons", json={"url": SALT, "pincode": "560001"}, headers=RAVI)
    assert r.json()["id"] != a["id"]
    again = env.c.post("/api/v1/comparisons", json={"url": SALT, "pincode": "560001"}, headers=ASHA)
    assert again.json()["id"] == a["id"] and again.json()["reused"] is True


def test_ownership_survives_restart(env: Env) -> None:
    cid = env.compare(SALT, ASHA)["id"]
    fresh = ComparisonService(
        env.store,
        build_adapters(FAST),
        ThreadFetchExecutor(build_adapters(FAST)),
        data_mode=DataMode.DEMO,
    )
    env.c.app.dependency_overrides[get_comparison_service] = lambda: fresh  # type: ignore[attr-defined]
    assert env.c.get(f"/api/v1/comparisons/{cid}", headers=RAVI).status_code == 404
    assert env.c.get(f"/api/v1/comparisons/{cid}", headers=ASHA).status_code == 200


# ------------------------------------------------------------------ history, saved, alerts


def test_history_is_per_user_and_paginated(env: Env) -> None:
    env.compare(SALT, ASHA)
    env.compare(PHONE, ASHA)
    env.compare(SALT, RAVI)
    env.compare(SALT)  # anonymous: in nobody's history
    page = env.c.get("/api/v1/search/history?limit=1", headers=ASHA).json()
    assert len(page["items"]) == 1 and page["next_cursor"] == "1"
    assert page["items"][0]["title"].startswith("Nimbus")  # newest first
    rest = env.c.get("/api/v1/search/history?cursor=1", headers=ASHA).json()
    assert [i["title"] for i in rest["items"]] == ["Saltwise Iodised Salt, 1 kg"]
    assert len(env.c.get("/api/v1/search/history", headers=RAVI).json()["items"]) == 1
    assert env.c.get("/api/v1/search/history").status_code == 401


def test_saved_products_are_idempotent_and_private(env: Env) -> None:
    slug = env.compare(SALT, ASHA)["product_slug"]
    first = env.c.post("/api/v1/saved-products", json={"product_slug": slug}, headers=ASHA)
    second = env.c.post("/api/v1/saved-products", json={"product_slug": slug}, headers=ASHA)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    saved = env.c.get("/api/v1/saved-products", headers=ASHA).json()
    assert [s["product_slug"] for s in saved] == [slug]
    assert env.c.get("/api/v1/saved-products", headers=RAVI).json() == []
    assert (
        env.c.delete(f"/api/v1/saved-products/{first.json()['id']}", headers=RAVI).status_code
        == 404
    )
    assert (
        env.c.delete(f"/api/v1/saved-products/{first.json()['id']}", headers=ASHA).status_code
        == 204
    )
    assert (
        env.c.post(
            "/api/v1/saved-products", json={"product_slug": "nope"}, headers=ASHA
        ).status_code
        == 404
    )


def test_alert_triggers_on_verified_price_only_once_a_day(env: Env) -> None:
    first = env.compare(SALT, ASHA)
    slug = first["product_slug"]
    below = env.c.post(
        "/api/v1/alerts",
        json={"product_slug": slug, "pincode": "560001", "target_price": "30"},
        headers=ASHA,
    ).json()
    never = env.c.post(
        "/api/v1/alerts",
        json={"product_slug": slug, "pincode": "560001", "target_price": "20"},
        headers=ASHA,
    ).json()
    other_pin = env.c.post(
        "/api/v1/alerts",
        json={"product_slug": slug, "pincode": "110001", "target_price": "30"},
        headers=ASHA,
    ).json()

    env.c.post(f"/api/v1/comparisons/{first['id']}/refresh", headers=ASHA)
    env.service.wait(
        env.store.find("comparisons", order_by="created_at", descending=True)[0]["id"].__str__()
    )
    alerts = {a["id"]: a for a in env.c.get("/api/v1/alerts", headers=ASHA).json()}
    hit = alerts[below["id"]]
    assert Decimal(hit["last_triggered_price"]) == Decimal("28.00")  # Amazon, fully verified
    assert hit["last_triggered_marketplace"] == "Amazon India"
    assert alerts[never["id"]]["last_triggered_at"] is None
    assert alerts[other_pin["id"]]["last_triggered_at"] is None
    triggered_at = hit["last_triggered_at"]

    env.c.post(f"/api/v1/comparisons/{first['id']}/refresh", headers=ASHA)
    env.service.wait(
        env.store.find("comparisons", order_by="created_at", descending=True)[0]["id"].__str__()
    )
    again = {a["id"]: a for a in env.c.get("/api/v1/alerts", headers=ASHA).json()}
    assert again[below["id"]]["last_triggered_at"] == triggered_at  # not re-triggered within a day
    actions = [r["action"] for r in env.store.find("audit_logs")]
    assert actions.count("price_alert_triggered") == 1


def test_alerts_are_private_and_validated(env: Env) -> None:
    slug = env.compare(SALT, ASHA)["product_slug"]
    a = env.c.post(
        "/api/v1/alerts",
        json={"product_slug": slug, "pincode": "560001", "target_price": "30"},
        headers=ASHA,
    ).json()
    assert (
        env.c.patch(
            f"/api/v1/alerts/{a['id']}", json={"is_active": False}, headers=RAVI
        ).status_code
        == 404
    )
    paused = env.c.patch(
        f"/api/v1/alerts/{a['id']}", json={"is_active": False}, headers=ASHA
    ).json()
    assert paused["is_active"] is False
    bad = env.c.post(
        "/api/v1/alerts",
        json={"product_slug": slug, "pincode": "12", "target_price": "30"},
        headers=ASHA,
    )
    assert bad.status_code == 409
    zero = env.c.post(
        "/api/v1/alerts",
        json={"product_slug": slug, "pincode": "560001", "target_price": "0"},
        headers=ASHA,
    )
    assert zero.status_code == 422


# ------------------------------------------------------------------ card personalisation


def test_best_card_uses_only_the_viewers_banks(env: Env) -> None:
    generic = env.compare(PHONE, ASHA)
    amazon = next(r for r in generic["results"] if r["marketplace"] == "AMAZON_IN")
    assert amazon["best_card"]["bank"] == "Demo Bank A" and generic["cards_personalized"] is False

    env.c.patch("/api/v1/me", headers=ASHA, json={"preferences": {"card_banks": ["Demo Bank C"]}})
    mine = env.c.get(f"/api/v1/comparisons/{generic['id']}", headers=ASHA).json()
    by = {r["marketplace"]: r for r in mine["results"]}
    assert mine["cards_personalized"] is True
    assert by["AMAZON_IN"]["best_card"]["bank"] == "Demo Bank C"  # ₹750 debit offer
    assert Decimal(by["AMAZON_IN"]["price_after_best_card"]) == Decimal("14249.00")
    assert by["FLIPKART"]["best_card"]["bank"] == "Demo Bank C"
    assert mine["summary"]["best_with_card"]["card"].startswith("Demo Bank C")
    # Every offer is still listed; only the "best" pick changes.
    assert len(by["AMAZON_IN"]["card_offers"]) == 3

    env.c.patch(
        "/api/v1/me",
        headers=ASHA,
        json={"preferences": {"card_banks": ["Demo Bank C"], "card_types": ["CREDIT"]}},
    )
    credit_only = env.c.get(f"/api/v1/comparisons/{generic['id']}", headers=ASHA).json()
    assert (
        next(r for r in credit_only["results"] if r["marketplace"] == "AMAZON_IN")["best_card"]
        is None
    )


# ------------------------------------------------------------------ admin


def test_admin_endpoints_require_admin(env: Env) -> None:
    for path in (
        "/admin/overview",
        "/admin/users",
        "/admin/integrations",
        "/admin/activity",
        "/admin/errors",
        "/admin/audit",
    ):
        assert env.c.get(f"/api/v1{path}").status_code == 401
        assert env.c.get(f"/api/v1{path}", headers=ASHA).status_code == 403
        assert env.c.get(f"/api/v1{path}", headers=ADMIN).status_code == 200, path


def test_admin_dashboard_data(env: Env) -> None:
    env.compare(PHONE, ASHA)  # BigBasket fails in the demo
    env.compare(SALT)
    o = env.c.get("/api/v1/admin/overview", headers=ADMIN).json()
    assert o["storage"] == "ok" and o["users"] == 2 and o["admins"] == 1
    assert o["comparisons_24h"] == 2
    assert o["marketplace_checks_24h"] == 10 and o["marketplace_failures_24h"] == 1

    rows = {
        r["marketplace"]: r for r in env.c.get("/api/v1/admin/integrations", headers=ADMIN).json()
    }
    assert rows["BIGBASKET"]["failures_24h"] == 1
    assert "server error" in rows["BIGBASKET"]["last_error"]
    assert rows["AMAZON_IN"]["state"] == "DEMO"

    errors = env.c.get("/api/v1/admin/errors", headers=ADMIN).json()
    assert errors[0]["marketplace_name"] == "BigBasket"
    activity = env.c.get("/api/v1/admin/activity", headers=ADMIN).json()
    assert {a["signed_in"] for a in activity} == {True, False}


def test_role_changes_are_audited_and_self_demotion_refused(env: Env) -> None:
    env.c.get("/api/v1/me", headers=ASHA)
    admin_id = env.c.get("/api/v1/me", headers=ADMIN).json()["id"]
    users = {u["email"]: u for u in env.c.get("/api/v1/admin/users", headers=ADMIN).json()["items"]}
    asha_id = users["asha@example.in"]["id"]

    r = env.c.patch(f"/api/v1/admin/users/{asha_id}", json={"role": "admin"}, headers=ADMIN)
    assert r.json()["role"] == "admin"
    assert env.c.get("/api/v1/admin/overview", headers=ASHA).status_code == 200
    entry = env.c.get("/api/v1/admin/audit", headers=ADMIN).json()[0]
    assert entry["action"] == "user_role_changed"
    assert entry["metadata"] == {"from": "user", "to": "admin"}
    assert entry["actor_id"] == admin_id

    self_demote = env.c.patch(
        f"/api/v1/admin/users/{admin_id}", json={"role": "user"}, headers=ADMIN
    )
    assert self_demote.status_code == 409
    assert (
        env.c.patch(
            f"/api/v1/admin/users/{asha_id}", json={"role": "user"}, headers=RAVI
        ).status_code
        == 403
    )
