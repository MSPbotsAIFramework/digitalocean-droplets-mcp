"""Thin async wrapper around DigitalOcean's REST API v2.

One client is built per request from the request-scoped token (see
middleware.py) -- never a module-level singleton holding a credential.
Retries 429/5xx with backoff honoring Retry-After; all other 4xx are not
retried. Connection + read timeouts keep a stalled upstream from hanging a
tool call past the platform's 120s budget.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from digitalocean_droplets_mcp.errors import UpstreamApiError

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0


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
    ) -> dict[str, Any]:
        """Issue one DigitalOcean API call, retrying 429/5xx with backoff.

        Raises UpstreamApiError for any non-2xx response that survives
        retries, or for a network-level failure (connect/read timeout,
        connection error), using status_code=0 to signal "no HTTP response".
        Returns {} for 204 No Content.
        """

        last_error: UpstreamApiError | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._http.request(method, path, params=params, json=json_body)
            except httpx.TimeoutException as exc:
                last_error = UpstreamApiError(0, f"timeout calling DigitalOcean API: {exc}")
                await self._backoff(attempt)
                continue
            except httpx.HTTPError as exc:
                last_error = UpstreamApiError(0, f"network error calling DigitalOcean API: {exc}")
                await self._backoff(attempt)
                continue

            if response.status_code < 400:
                if response.status_code == 204 or not response.content:
                    return {}
                return response.json()

            retry_after = response.headers.get("Retry-After")
            message = self._extract_message(response)
            last_error = UpstreamApiError(response.status_code, message, retry_after)

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
    async def _backoff(attempt: int, retry_after: str | None = None) -> None:
        if retry_after is not None:
            try:
                await asyncio.sleep(min(float(retry_after), 30.0))
                return
            except ValueError:
                pass
        await asyncio.sleep(BACKOFF_BASE_SECONDS * (2**attempt))
