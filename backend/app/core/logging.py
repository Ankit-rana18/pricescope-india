"""Structured JSON logging with secret/PII redaction."""

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEYS = re.compile(
    r"(pass(word)?|secret|token|authorization|api[_-]?key|cookie|credential)", re.IGNORECASE
)
REDACTED = "[REDACTED]"


def redact_sensitive(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Replace values of sensitive-looking keys, recursively, before they are emitted."""

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (REDACTED if _SENSITIVE_KEYS.search(str(k)) else scrub(v))
                for k, v in value.items()
            }
        if isinstance(value, list | tuple):
            return [scrub(v) for v in value]
        return value

    for key in list(event_dict):
        if key != "event" and _SENSITIVE_KEYS.search(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = scrub(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    log_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_sensitive,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
