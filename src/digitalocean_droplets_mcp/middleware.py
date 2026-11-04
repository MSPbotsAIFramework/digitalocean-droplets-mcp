"""Request-scoped credential handling.

Credentials are read exclusively from the X-DigitalOcean-Api-Token header,
set on a contextvars.ContextVar for the lifetime of the request, and reset
in a finally block. There is no environment-variable fallback: a request
with no header is rejected with 401 before any tool runs, and a module-level
global is never used to hold a credential (that would leak across tenants
under concurrency).
"""

from __future__ import annotations

import contextvars
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

TOKEN_HEADER = "X-DigitalOcean-Api-Token"

_token_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("digitalocean_api_token", default=None)


def current_token() -> str | None:
    """The DigitalOcean API token for the in-flight request, or None."""

    return _token_var.get()


async def credential_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Starlette middleware: enforce the credential header on /mcp only.

    /health must stay reachable with no credential (SOP 1.1: it is a pure
    local liveness probe, not a DigitalOcean reachability check).
    """

    if request.url.path != "/mcp":
        return await call_next(request)

    token = request.headers.get(TOKEN_HEADER)
    if not token:
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "unauthorized",
                    "message": f"Missing required header: {TOKEN_HEADER}",
                    "retryable": False,
                },
                "required_headers": [TOKEN_HEADER],
            },
        )

    reset_token = _token_var.set(token)
    try:
        return await call_next(request)
    finally:
        _token_var.reset(reset_token)
