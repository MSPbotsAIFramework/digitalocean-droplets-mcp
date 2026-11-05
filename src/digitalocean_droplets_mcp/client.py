"""Thin async wrapper around DigitalOcean's REST API v2.

One client is built per request from the request-scoped token (see
middleware.py) -- never a module-level singleton holding a credential.
Retries 429/5xx with backoff honoring Retry-After; all other 4xx are not
retried. Connection + read timeouts keep a stalled upstream from hanging a
tool call past the platform's 120s budget, and the whole retry loop is also
capped by OVERALL_BUDGET_SECONDS so the combination of per-attempt timeouts
and backoff sleeps can never itself exceed that budget (see `request()`).

Logs one structured record per call (SOP SS6): tool name, method, path,
outcome, duration_ms, attempt count, and DigitalOcean's own request id when
the response carries one -- never the token value or request/response bodies.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from digitalocean_droplets_mcp.errors import UpstreamApiError, error_code_for_status
from digitalocean_droplets_mcp.logging_config import log_event
from digitalocean_droplets_mcp.middleware import current_request_id

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0

# Caps the whole retry loop (every attempt + every backoff sleep) well under the
# platform's mandatory <120s-per-tool-call budget, leaving margin for MCP-level
# serialization/transport overhead on top of this call. Enforced with
# asyncio.wait_for around the entire loop rather than per-attempt arithmetic,
# so the guarantee holds regardless of how MAX_RETRIES/timeouts change later.
OVERALL_BUDGET_SECONDS = 100.0


class DigitalOceanClient:
    """One instance per request; never shared across requests."""

    def __init__(self, token: str, base_url: str, transport: httpx.BaseTransport | None = None) -> None:
        # `transport` is a testability hook (tests/test_tools.py mocks the DigitalOcean
        # API with httpx.MockTransport); production code never passes it, so it always
        # makes real network calls to `base_url`.
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=READ_TIMEOUT, pool=READ_TIMEOUT),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "DigitalOceanClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        """Issue one DigitalOcean API call, retrying 429/5xx with backoff.

        Raises UpstreamApiError for any non-2xx response that survives
        retries, for a network-level failure (connect/read timeout,
        connection error), or for exhausting OVERALL_BUDGET_SECONDS --
        all using status_code=0 for "no HTTP response" cases.
        Returns {} for 204 No Content.

        `tool_name` is the calling MCP tool's name, used only for the
        structured call log below.
        """

        start = time.monotonic()
        try:
            body, status_code, do_request_id, attempts = await asyncio.wait_for(
                self._request_with_retries(method, path, params=params, json_body=json_body),
                timeout=OVERALL_BUDGET_SECONDS,
            )
        except asyncio.TimeoutError:
            self._log(
                tool_name, method, path,
                status_code=0, error_code="upstream_error",
                duration_ms=self._elapsed_ms(start), attempts=MAX_RETRIES + 1, do_request_id=None,
            )
            raise UpstreamApiError(
                0, f"DigitalOcean API call exceeded the {OVERALL_BUDGET_SECONDS:.0f}s retry budget"
            ) from None
        except UpstreamApiError as exc:
            self._log(
                tool_name, method, path,
                status_code=exc.status_code, error_code=error_code_for_status(exc.status_code),
                duration_ms=self._elapsed_ms(start), attempts=exc.attempts, do_request_id=exc.do_request_id,
            )
            raise

        self._log(
            tool_name, method, path,
            status_code=status_code, error_code=None,
            duration_ms=self._elapsed_ms(start), attempts=attempts, do_request_id=do_request_id,
        )
        return body

    async def _request_with_retries(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], int, str | None, int]:
        """The actual attempt/backoff loop. Returns (body, status_code,
        digitalocean_request_id, attempts) on success; raises UpstreamApiError
        (carrying the same attempts/request-id detail) when every attempt is
        exhausted or a non-retryable status is returned."""

        last_error: UpstreamApiError | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._http.request(method, path, params=params, json=json_body)
            except httpx.TimeoutException as exc:
                last_error = UpstreamApiError(0, f"timeout calling DigitalOcean API: {exc}", attempts=attempt + 1)
                if attempt < MAX_RETRIES:
                    await self._backoff(attempt)
                    continue
                break
            except httpx.HTTPError as exc:
                last_error = UpstreamApiError(
                    0, f"network error calling DigitalOcean API: {exc}", attempts=attempt + 1
                )
                if attempt < MAX_RETRIES:
                    await self._backoff(attempt)
                    continue
                break

            do_request_id = self._extract_request_id(response)

            if response.status_code < 400:
                attempts = attempt + 1
                if response.status_code == 204 or not response.content:
                    return {}, response.status_code, do_request_id, attempts
                return response.json(), response.status_code, do_request_id, attempts

            retry_after = response.headers.get("Retry-After")
            message = self._extract_message(response)
            last_error = UpstreamApiError(
                response.status_code, message, retry_after, attempts=attempt + 1, do_request_id=do_request_id
            )

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < MAX_RETRIES:
                    await self._backoff(attempt, retry_after)
                    continue
            break

        assert last_error is not None
        raise last_error

    @staticmethod
    def _extract_message(response: httpx.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict) and "message" in body:
                return str(body["message"])
        except ValueError:
            pass
        return f"DigitalOcean API returned HTTP {response.status_code}"

    @staticmethod
    def _extract_request_id(response: httpx.Response) -> str | None:
        """Best-effort: DigitalOcean does not document a dedicated request-id
        response header, so this checks the header names vendors commonly use
        and returns None rather than guessing when none are present."""

        for header in ("x-request-id", "request-id", "x-do-request-id"):
            value = response.headers.get(header)
            if value:
                return value
        return None

    @staticmethod
    async def _backoff(attempt: int, retry_after: str | None = None) -> None:
        if retry_after is not None:
            try:
                await asyncio.sleep(min(float(retry_after), 30.0))
                return
            except ValueError:
                pass
        await asyncio.sleep(BACKOFF_BASE_SECONDS * (2**attempt))

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        return round((time.monotonic() - start) * 1000, 1)

    @staticmethod
    def _log(
        tool_name: str | None,
        method: str,
        path: str,
        *,
        status_code: int,
        error_code: str | None,
        duration_ms: float,
        attempts: int,
        do_request_id: str | None,
    ) -> None:
        fields: dict[str, Any] = {
            "request_id": current_request_id(),
            "tool_name": tool_name,
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "attempts": attempts,
        }
        if error_code is not None:
            fields["error_code"] = error_code
        if do_request_id is not None:
            fields["digitalocean_request_id"] = do_request_id
        log_event(logger, "digitalocean_api_call", **fields)
