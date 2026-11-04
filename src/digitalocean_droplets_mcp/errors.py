"""Structured error envelope shared by every tool.

Tools never raise exceptions to the caller -- every failure is returned as a
JSON string of the shape {"error": {"code", "message", "retryable"}}, using
the fixed vocabulary below. See the SOP (Vendor MCP development) section 4.
"""

from __future__ import annotations

import json

ERROR_CODES = (
    "not_configured",
    "unauthorized",
    "not_found",
    "invalid_argument",
    "rate_limited",
    "upstream_error",
)


class UpstreamApiError(Exception):
    """Raised by api_client.py when DigitalOcean returns a non-2xx response."""

    def __init__(self, status_code: int, message: str, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.retry_after = retry_after


def error_envelope(code: str, message: str, retryable: bool) -> str:
    """Serialize a structured error envelope. Never call json.dumps(indent=...)."""

    if code not in ERROR_CODES:
        raise ValueError(f"unknown error code: {code}")
    return json.dumps(
        {"error": {"code": code, "message": message, "retryable": retryable}},
        separators=(",", ":"),
        ensure_ascii=False,
    )


def map_status_to_error(status_code: int, message: str, retry_after: str | None = None) -> str:
    """Map a DigitalOcean HTTP status code to the fixed error vocabulary."""

    if status_code == 401 or status_code == 403:
        return error_envelope("unauthorized", message, retryable=False)
    if status_code == 404:
        return error_envelope("not_found", message, retryable=False)
    if status_code == 422 or status_code == 400:
        return error_envelope("invalid_argument", message, retryable=False)
    if status_code == 429:
        detail = message
        if retry_after:
            detail = f"{message} (retry_after={retry_after})"
        return error_envelope("rate_limited", detail, retryable=True)
    if status_code >= 500:
        return error_envelope("upstream_error", message, retryable=True)
    return error_envelope("upstream_error", message, retryable=True)


def handle_upstream_error(exc: UpstreamApiError) -> str:
    """Convert a raised UpstreamApiError into the structured error envelope.

    status_code == 0 means client.py never got an HTTP response at all
    (timeout or connection error), which maps to upstream_error directly.
    """

    if exc.status_code == 0:
        return network_error(exc.message)
    return map_status_to_error(exc.status_code, exc.message, exc.retry_after)


def network_error(message: str) -> str:
    """A connection failure or timeout talking to DigitalOcean's API."""

    return error_envelope("upstream_error", message, retryable=True)


def invalid_argument(message: str) -> str:
    """A tool-level validation failure caught before any outbound call."""

    return error_envelope("invalid_argument", message, retryable=False)


def not_configured(message: str) -> str:
    """Server-side configuration is missing (credential middleware normally
    intercepts this with a 401 before a tool ever runs)."""

    return error_envelope("not_configured", message, retryable=False)
