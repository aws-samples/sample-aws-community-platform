"""Input validation helpers (SECURITY-05).

Reference convention — copied per service by the scaffold generator (FQ1).
Type/length/format checks + basic sanitization; raises ValidationError.
"""
from __future__ import annotations

import re
from typing import Any

from .errors import ValidationError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Reject angle brackets to prevent stored/reflected XSS in user-supplied strings.
_UNSAFE_HTML_RE = re.compile(r"[<>]")


def require(condition: bool, field: str, message: str) -> None:
    if not condition:
        raise ValidationError(message="Validation failed.", details=[{"field": field, "message": message}])


def require_str(value: Any, field: str, *, max_len: int, min_len: int = 1) -> str:
    require(isinstance(value, str), field, "must be a string")
    require(min_len <= len(value) <= max_len, field, f"length must be {min_len}-{max_len}")
    require(not _UNSAFE_HTML_RE.search(value), field, "must not contain '<' or '>'")
    return value


def require_email(value: Any, field: str = "email") -> str:
    require(isinstance(value, str) and bool(_EMAIL_RE.match(value)), field, "must be a valid email")
    return value


def require_enum(value: Any, field: str, allowed: set[str]) -> str:
    require(value in allowed, field, f"must be one of {sorted(allowed)}")
    return value


def require_int(value: Any, field: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    require(isinstance(value, int) and not isinstance(value, bool), field, "must be an integer")
    if minimum is not None:
        require(value >= minimum, field, f"must be >= {minimum}")
    if maximum is not None:
        require(value <= maximum, field, f"must be <= {maximum}")
    return value


def max_body_size(raw: str | bytes, field: str = "body", *, limit_bytes: int = 1_000_000) -> None:
    size = len(raw.encode() if isinstance(raw, str) else raw)
    require(size <= limit_bytes, field, f"payload exceeds {limit_bytes} bytes")


def require_bool_like(value: Any, field: str) -> bool:
    """Accept a real bool, or (for form-style callers) the strings 'true'/'false'."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    require(False, field, "must be a boolean")
    return False  # unreachable; keeps type-checkers happy
