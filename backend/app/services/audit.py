"""Audit log: who did what, for security-relevant actions (role changes, admin actions)."""

from typing import Any

import structlog

from app.storage.base import TableStore

log = structlog.get_logger(__name__)


def audit(
    store: TableStore,
    action: str,
    *,
    actor_id: Any = None,
    target: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record an audit entry. Raw IP addresses are never stored."""
    try:
        store.insert(
            "audit_logs",
            {"actor_id": actor_id, "action": action, "target": target, "metadata": metadata or {}},
        )
    except Exception:  # the action already happened; never hide it behind an audit failure
        log.exception("audit_write_failed", action=action, target=target)
