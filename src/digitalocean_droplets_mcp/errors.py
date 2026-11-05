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
    """Raised by client.py when DigitalOcean returns a non-2xx response, a
    network/timeout failure occurs, or the overall retry budget is spent.

    `attempts` and `do_request_id` are additive detail used only by client.py's
    structured call log (SOP SS6); tool-level error handling (handle_upstream_error)
    only ever reads status_code/message/retry_after.
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        retry_after: str | None = None,
        *,
        attempts: int = 1,
        do_request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.retry_after = retry_after
        self.attempts = attempts
        self.do_request_id = do_request_id


def error_envelope(code: str, message: str, retryable: bool) -> str:
    """Serialize a structured error envelope. Never call json.dumps(indent=...)."""

    if code not in ERROR_CODES:
        raise ValueError(f"unknown error code: {code}")
    return json.dumps(
        {"error": {"code": code, "message": message, "retryable": retryable}},
        separators=(",", ":"),
        ensure_ascii=False,
    )


def error_code_for_status(status_code: int) -> str:
    """Map a DigitalOcean HTTP status code to this project's fixed error-code
    vocabulary. `status_code == 0` means no HTTP response was ever received
    (timeout or connection error, see client.py) and maps to `upstream_error`.

    Shared by `map_status_to_error` (tool-facing error envelope) and client.py's
    structured call log, so the two never drift apart.
    """

    if status_code in (401, 403):
        return "unauthorized"
    if status_code == 404:
        return "not_found"
    if status_code in (422, 400):
        return "invalid_argument"
    if status_code == 429:
        return "rate_limited"
    return "upstream_error"


def map_status_to_error(status_code: int, message: str, retry_after: str | None = None) -> str:
    """Map a DigitalOcean HTTP status code to the fixed error vocabulary."""

    code = error_code_for_status(status_code)
    if code == "rate_limited" and retry_after:
        message = f"{message} (retry_after={retry_after})"
    retryable = code in ("rate_limited", "upstream_error")
    return error_envelope(code, message, retryable=retryable)


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
