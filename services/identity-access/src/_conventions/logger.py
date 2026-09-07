"""Structured JSON logging with correlation id (SECURITY-03, NFR-OBS-1).

Reference convention — copied per service by the scaffold generator (FQ1).
Emits single-line JSON to stdout (CloudWatch), never logging secrets/PII.
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

# Keys that must never be logged (SECURITY-03).
_REDACT = {"password", "token", "authorization", "secret", "otp", "access_token", "id_token"}


def set_correlation_id(correlation_id: str | None) -> None:
    _correlation_id.set(correlation_id or "-")


def get_correlation_id() -> str:
    return _correlation_id.get()


def _redact(obj):
    if isinstance(obj, dict):
        return {k: ("***" if k.lower() in _REDACT else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "message": record.getMessage(),
            "correlationId": get_correlation_id(),
            "logger": record.name,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(_redact(extra))
        return json.dumps(payload, default=str)


def get_logger(name: str = "app") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log(logger: logging.Logger, level: int, message: str, **fields) -> None:
    """Log with structured extra fields (auto-redacted)."""
    logger.log(level, message, extra={"extra_fields": fields})
