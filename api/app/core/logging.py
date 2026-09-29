"""Structured logging with a request ID and secret redaction."""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

try:
    import structlog
except ImportError:  # The dependency-light launcher uses structured stdlib logging.
    structlog = None
import json
import datetime as dt

REDACTED = "[redacted]"
SENSITIVE_KEYS = {
    "password",
    "secret_key",
    "tron_api_key",
    "api_key",
    "authorization",
    "cookie",
    "set-cookie",
    "session",
    "token",  # noqa: S105 - a log key name, not a credential
}


def _redact(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = REDACTED
    return event_dict


def configure_logging(level: int = logging.INFO) -> None:
    if structlog is None:
        logging.basicConfig(level=level, format="%(message)s")
        return
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name) if structlog is not None else _StdlibLogger(name)


class _StdlibLogger:
    """Small structured logger for the dependency-light runtime, not a test stub."""
    def __init__(self, name: str, **context: Any) -> None:
        self.logger = logging.getLogger(name)
        self.context = context

    def bind(self, **context: Any) -> "_StdlibLogger":
        return _StdlibLogger(self.logger.name, **(self.context | context))

    def _emit(self, level: int, event: str, **values: Any) -> None:
        record = dict(self.context, **values)
        record.update(event=event, timestamp=dt.datetime.now(dt.UTC).isoformat())
        _redact(None, "", record)
        self.logger.log(level, json.dumps(record, default=str))

    def info(self, event: str, **values: Any) -> None:
        self._emit(logging.INFO, event, **values)

    def warning(self, event: str, **values: Any) -> None:
        self._emit(logging.WARNING, event, **values)

    def error(self, event: str, **values: Any) -> None:
        self._emit(logging.ERROR, event, **values)

    def debug(self, event: str, **values: Any) -> None:
        self._emit(logging.DEBUG, event, **values)

    def exception(self, event: str, **values: Any) -> None:
        self._emit(logging.ERROR, event, **values)
