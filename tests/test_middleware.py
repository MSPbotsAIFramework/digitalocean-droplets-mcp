"""Tests for the credential middleware: missing-header 401, /health independence
from any DigitalOcean credential/reachability, and request-level token isolation
under real concurrency.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from digitalocean_droplets_mcp.middleware import TOKEN_HEADER
from conftest import build_app, no_call_expected_handler, run_lifespan

HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _tools_list_payload(request_id: int) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/list"}


# ---------------------------------------------------------------------------
# TC-DOD-018 (AC9)
# ---------------------------------------------------------------------------


async def test_missing_credential_header_returns_401_before_upstream_call():
    app = build_app(no_call_expected_handler)
    async with run_lifespan(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            response = await http.post("/mcp", headers=HEADERS, json=_tools_list_payload(1))

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert TOKEN_HEADER in body["required_headers"]


# ---------------------------------------------------------------------------
# TC-DOD-024 (AC12)
# ---------------------------------------------------------------------------


async def test_health_endpoint_returns_200_without_do_credential_or_reachability():
    app = build_app(no_call_expected_handler)
    async with run_lifespan(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            # No X-DigitalOcean-Api-Token header at all, and the mocked DigitalOcean
            # transport raises AssertionError on any call -- /health must never reach it.
            response = await http.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# TC-DOD-023 (AC11)
# ---------------------------------------------------------------------------


async def test_concurrent_requests_with_different_tokens_never_cross():
    """Two concurrent /mcp requests carrying two different tenants' tokens must
    never have their outbound DigitalOcean call, or their response, carry the
    other tenant's token or data -- exercised at the real HTTP + ContextVar layer,
    not just unit-level, since that is where a global/module-level credential
    leak would actually manifest under concurrency.
    """

    expected_token_by_droplet_id = {101: "token-tenant-a", 202: "token-tenant-b"}

    def handler(request: httpx.Request) -> httpx.Response:
        droplet_id = int(request.url.path.rsplit("/", 1)[-1])
        seen_token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        expected = expected_token_by_droplet_id[droplet_id]

        if seen_token != expected:
            return httpx.Response(
                500, json={"id": "test_failure", "message": f"token crossover: droplet {droplet_id} saw {seen_token!r}"}
            )
        return httpx.Response(
            200,
            json={
                "droplet": {
                    "id": droplet_id,
                    "name": f"d{droplet_id}",
                    "status": "active",
                    "region": {"slug": "nyc3"},
                    "size_slug": "s-1vcpu-1gb",
                    "image": {"slug": "ubuntu"},
                    "networks": {},
                }
            },
        )

    app = build_app(handler)

    async def call_tool(http: httpx.AsyncClient, request_id: int, token: str, droplet_id: int) -> httpx.Response:
        headers = {**HEADERS, TOKEN_HEADER: token}
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "digitalocean_get_droplet", "arguments": {"droplet_id": droplet_id}},
        }
        return await http.post("/mcp", headers=headers, json=payload)

    async with run_lifespan(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            response_a, response_b = await asyncio.gather(
                call_tool(http, 1, "token-tenant-a", 101),
                call_tool(http, 2, "token-tenant-b", 202),
            )

    for response in (response_a, response_b):
        assert response.status_code == 200
        body = _parse_sse_json(response.text)
        tool_text = body["result"]["content"][0]["text"]
        result = json.loads(tool_text)
        assert "error" not in result, f"unexpected error (likely token crossover): {result}"


def _parse_sse_json(text: str) -> dict:
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    raise AssertionError(f"no data: line found in SSE response: {text!r}")
