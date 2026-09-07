"""Fail-closed error handling (SECURITY-15).

Reference convention — copied per service by the scaffold generator (FQ1).
Domain errors map to safe HTTP responses using the error-response contract;
the global handler catches everything else and returns a generic 500.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .logger import get_correlation_id, get_logger

_logger = get_logger("errors")


@dataclass
class AppError(Exception):
    """Base application error. `code`/`status` map to the error-response contract."""
    code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred."
    status: int = 500
    details: list | None = None


class ValidationError(AppError):
    def __init__(self, message: str = "Invalid input.", details: list | None = None):
        super().__init__(code="VALIDATION_ERROR", message=message, status=400, details=details)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required."):
        super().__init__(code="UNAUTHORIZED", message=message, status=401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "You do not have permission to perform this action."):
        super().__init__(code="FORBIDDEN", message=message, status=403)


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found."):
        super().__init__(code="NOT_FOUND", message=message, status=404)


class NotImplementedError501(AppError):
    """Returned by endpoints not yet implemented (FQ8, BR-17)."""
    def __init__(self, message: str = "This feature is not yet available."):
        super().__init__(code="NOT_IMPLEMENTED", message=message, status=501)


def _response(status: int, code: str, message: str, details=None) -> dict:
    body = {"code": code, "message": message, "correlationId": get_correlation_id()}
    if details:
        body["details"] = details
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def to_response(err: Exception) -> dict:
    """Map any exception to a safe API Gateway proxy response (generic messages only)."""
    if isinstance(err, AppError):
        return _response(err.status, err.code, err.message, err.details)
    # Unknown error: log internally, return generic 500 (no internals leaked).
    _logger.exception("Unhandled error")
    return _response(500, "INTERNAL_ERROR", "An unexpected error occurred.")


def global_handler(handler):
    """Decorator: wrap a Lambda handler so no exception escapes (fail-closed)."""
    def wrapper(event, context):
        try:
            return handler(event, context)
        except Exception as err:  # noqa: BLE001 — top-level fail-closed boundary
            return to_response(err)
    return wrapper
