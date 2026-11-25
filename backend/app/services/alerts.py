"""Price-drop alerts: checked whenever a comparison of the alert's product is saved.

An alert triggers when the cheapest *fully verified* final price (exact match, in stock,
every fee reported, delivery to the PIN verified) at the alert's PIN code is at or below
its target. Estimated or unverified prices never trigger an alert. An alert triggers at
most once a day. Email delivery isn't built yet: triggers are recorded on the alert (the
user sees them in the app) and in the audit log.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog

from app.storage.base import TableStore

log = structlog.get_logger(__name__)
RETRIGGER_AFTER = timedelta(hours=24)


class AlertService:
    def __init__(self, store: TableStore) -> None:
        self._store = store

    def evaluate(
        self,
        variant_id: Any,
        pincode: str,
        cheapest_price: Decimal | None,
        cheapest_marketplace: str | None,
    ) -> int:
        """Trigger matching alerts; returns how many triggered."""
        if cheapest_price is None:
            return 0
        now = datetime.now(UTC)
        triggered = 0
        for alert in self._store.find(
            "price_alerts", {"variant_id": variant_id, "pincode": pincode, "is_active": True}
        ):
            if cheapest_price > alert["target_price"]:
                continue
            last = alert.get("last_triggered_at")
            if last is not None and now - last < RETRIGGER_AFTER:
                continue
            self._store.update(
                "price_alerts",
                alert["id"],
                {
                    "last_triggered_at": now,
                    "last_triggered_price": cheapest_price,
                    "last_triggered_marketplace": cheapest_marketplace,
                },
            )
            self._store.insert(
                "audit_logs",
                {
                    "actor_id": None,
                    "action": "price_alert_triggered",
                    "target": f"price_alert:{alert['id']}",
                    "metadata": {
                        "user_id": str(alert["user_id"]),
                        "price": str(cheapest_price),
                        "target_price": str(alert["target_price"]),
                        "marketplace": cheapest_marketplace,
                        "email": "not sent: email delivery is not configured yet",
                    },
                },
            )
            triggered += 1
        if triggered:
            log.info("price_alerts_triggered", count=triggered, pincode=pincode)
        return triggered
