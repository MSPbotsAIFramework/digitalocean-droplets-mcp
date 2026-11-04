"""Unit tests for the 13 DigitalOcean Droplets tools: tools/list snapshot,
local validation, and the DigitalOcean-status -> error-envelope mapping.
All DigitalOcean calls are mocked (httpx.MockTransport) -- no real account needed.
"""

from __future__ import annotations

import json

import httpx
from fastmcp import Client

from conftest import DEFAULT_TEST_TOKEN as TOKEN
from conftest import build_app, build_mcp, no_call_expected_handler, run_lifespan
from digitalocean_droplets_mcp.middleware import TOKEN_HEADER


async def call(mcp, name: str, args: dict) -> str:
    async with Client(mcp) as client:
        result = await client.call_tool(name, args)
    return result.data


# ---------------------------------------------------------------------------
# TC-DOD-001 / TC-DOD-002 (AC1)
# ---------------------------------------------------------------------------


async def test_list_droplets_returns_all_droplets():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/droplets"
        return httpx.Response(
            200,
            json={
                "droplets": [
                    {
                        "id": 1,
                        "name": "web-01",
                        "status": "active",
                        "region": {"slug": "nyc3"},
                        "size_slug": "s-1vcpu-1gb",
                        "image": {"slug": "ubuntu-24-04-x64"},
                        "networks": {"v4": []},
                    },
                    {
                        "id": 2,
                        "name": "web-02",
                        "status": "active",
                        "region": {"slug": "nyc3"},
                        "size_slug": "s-1vcpu-1gb",
                        "image": {"slug": "ubuntu-24-04-x64"},
                        "networks": {"v4": []},
                    },
                ],
                "links": {},
                "meta": {"total": 2},
            },
        )

    mcp = build_mcp(handler)
    body = json.loads(await call(mcp, "digitalocean_list_droplets", {}))
    assert [d["id"] for d in body["droplets"]] == [1, 2]
    assert body["has_more"] is False


async def test_list_droplets_empty_account_returns_empty_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"droplets": [], "links": {}, "meta": {"total": 0}})

    mcp = build_mcp(handler)
    body = json.loads(await call(mcp, "digitalocean_list_droplets", {}))
    assert body["droplets"] == []
    assert "error" not in body


# ---------------------------------------------------------------------------
# TC-DOD-003 / TC-DOD-004 (AC2)
# ---------------------------------------------------------------------------


async def test_get_droplet_returns_full_record():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/droplets/123"
        return httpx.Response(
            200,
            json={
                "droplet": {
                    "id": 123,
                    "name": "web-01",
                    "status": "active",
                    "region": {"slug": "nyc3"},
                    "size_slug": "s-1vcpu-1gb",
                    "image": {"slug": "ubuntu-24-04-x64"},
                    "networks": {"v4": [{"ip_address": "203.0.113.1"}]},
                }
            },
        )

    mcp = build_mcp(handler)
    body = json.loads(await call(mcp, "digitalocean_get_droplet", {"droplet_id": 123}))
    assert body == {
        "id": 123,
        "name": "web-01",
        "status": "active",
        "region": "nyc3",
        "size": "s-1vcpu-1gb",
        "image": "ubuntu-24-04-x64",
        "networks": {"v4": [{"ip_address": "203.0.113.1"}]},
    }


async def test_get_droplet_unknown_id_returns_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"id": "not_found", "message": "The resource you requested could not be found."})

    mcp = build_mcp(handler)
    body = json.loads(await call(mcp, "digitalocean_get_droplet", {"droplet_id": 999999}))
    assert body["error"]["code"] == "not_found"
    assert body["error"]["retryable"] is False


# ---------------------------------------------------------------------------
# TC-DOD-006 (AC3)
# ---------------------------------------------------------------------------


async def test_create_droplet_missing_required_field_rejected_locally():
    mcp = build_mcp(no_call_expected_handler)
    body = json.loads(
        await call(
            mcp,
            "digitalocean_create_droplet",
            {"name": "web-01", "region": "nyc3", "size": "", "image": "ubuntu-24-04-x64"},
        )
    )
    assert body["error"]["code"] == "invalid_argument"
    assert "size" in body["error"]["message"]


# ---------------------------------------------------------------------------
# TC-DOD-008 / TC-DOD-009 (AC4)
# ---------------------------------------------------------------------------


async def test_delete_droplet_unknown_id_returns_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(404, json={"id": "not_found", "message": "The resource you requested could not be found."})

    mcp = build_mcp(handler)
    body = json.loads(await call(mcp, "digitalocean_delete_droplet", {"droplet_id": 999999}))
    assert body["error"]["code"] == "not_found"


async def test_delete_droplet_schema_has_no_bulk_parameter():
    mcp = build_mcp(no_call_expected_handler)
    tools = await mcp.get_tools()
    schema = tools["digitalocean_delete_droplet"].parameters
    properties = set(schema.get("properties", {}))
    assert properties == {"droplet_id"}
    assert schema.get("properties", {}).get("droplet_id", {}).get("type") == "integer"


# ---------------------------------------------------------------------------
# TC-DOD-011 (AC5)
# ---------------------------------------------------------------------------


async def test_droplet_action_unsupported_type_rejected_locally():
    mcp = build_mcp(no_call_expected_handler)
    body = json.loads(
        await call(mcp, "digitalocean_droplet_action", {"droplet_id": 1, "type": "change_kernel"})
    )
    assert body["error"]["code"] == "invalid_argument"
    assert "change_kernel" in body["error"]["message"]


# ---------------------------------------------------------------------------
# TC-DOD-015 / 016 / 017 (AC8)
# ---------------------------------------------------------------------------


def _paged_handler(resource_key: str, total_items: int):
    def handler(request: httpx.Request) -> httpx.Response:
        per_page = int(request.url.params.get("per_page", 50))
        items = [{"slug": f"{resource_key}-{i}"} for i in range(min(per_page, total_items))]
        links = {"pages": {"next": "..."}} if total_items > per_page else {}
        return httpx.Response(200, json={resource_key: items, "links": links, "meta": {"total": total_items}})

    return handler


async def test_list_regions_respects_limit_and_has_more():
    mcp = build_mcp(_paged_handler("regions", total_items=120))
    body = json.loads(await call(mcp, "digitalocean_list_regions", {"limit": 10}))
    assert len(body["regions"]) == 10
    assert body["has_more"] is True

    mcp_all = build_mcp(_paged_handler("regions", total_items=5))
    body_all = json.loads(await call(mcp_all, "digitalocean_list_regions", {"limit": 50}))
    assert len(body_all["regions"]) == 5
    assert body_all["has_more"] is False


async def test_list_sizes_respects_limit_and_has_more():
    mcp = build_mcp(_paged_handler("sizes", total_items=300))
    body = json.loads(await call(mcp, "digitalocean_list_sizes", {"limit": 500}))
    # hard cap is 200 even though the caller asked for 500
    assert len(body["sizes"]) == 200
    assert body["has_more"] is True


async def test_list_images_respects_limit_and_has_more():
    mcp = build_mcp(_paged_handler("images", total_items=30))
    body = json.loads(await call(mcp, "digitalocean_list_images", {"limit": 50}))
    assert len(body["images"]) == 30
    assert body["has_more"] is False


# ---------------------------------------------------------------------------
# TC-DOD-019..022 (AC10)
# ---------------------------------------------------------------------------


async def test_upstream_401_maps_to_unauthorized():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"id": "unauthorized", "message": "Unable to authenticate you."})

    mcp = build_mcp(handler)
    body = json.loads(await call(mcp, "digitalocean_get_droplet", {"droplet_id": 1}))
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["retryable"] is False


async def test_upstream_422_maps_to_invalid_argument():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"id": "unprocessable_entity", "message": "name is required"})

    mcp = build_mcp(handler)
    body = json.loads(
        await call(
            mcp,
            "digitalocean_create_droplet",
            {"name": "x", "region": "nyc3", "size": "s-1vcpu-1gb", "image": "ubuntu-24-04-x64"},
        )
    )
    assert body["error"]["code"] == "invalid_argument"


async def test_upstream_429_maps_to_rate_limited_with_retry_after():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "7"}, json={"id": "too_many_requests", "message": "API Rate limit exceeded"})

    mcp = build_mcp(handler)
    body = json.loads(await call(mcp, "digitalocean_get_droplet", {"droplet_id": 1}))
    assert body["error"]["code"] == "rate_limited"
    assert body["error"]["retryable"] is True
    assert "7" in body["error"]["message"]


async def test_upstream_5xx_and_network_failure_map_to_upstream_error():
    def handler_5xx(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"id": "service_unavailable", "message": "DigitalOcean is unavailable"})

    mcp = build_mcp(handler_5xx)
    body = json.loads(await call(mcp, "digitalocean_get_droplet", {"droplet_id": 1}))
    assert body["error"]["code"] == "upstream_error"
    assert body["error"]["retryable"] is True

    def handler_network_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    mcp_network = build_mcp(handler_network_failure)
    body_network = json.loads(await call(mcp_network, "digitalocean_get_droplet", {"droplet_id": 1}))
    assert body_network["error"]["code"] == "upstream_error"
    assert body_network["error"]["retryable"] is True


# ---------------------------------------------------------------------------
# TC-DOD-025 (AC13) -- stateless, tools/list returns all 13 tools
# ---------------------------------------------------------------------------

EXPECTED_TOOL_NAMES = {
    "digitalocean_list_droplets",
    "digitalocean_get_droplet",
    "digitalocean_create_droplet",
    "digitalocean_delete_droplet",
    "digitalocean_droplet_action",
    "digitalocean_list_droplet_actions",
    "digitalocean_get_action",
    "digitalocean_list_snapshots",
    "digitalocean_delete_snapshot",
    "digitalocean_list_backups",
    "digitalocean_list_regions",
    "digitalocean_list_sizes",
    "digitalocean_list_images",
}


async def test_initialize_and_tools_list_are_stateless_and_return_all_tools():
    """Exercises the real HTTP stack (not just the in-process tool registry):
    a fresh connection with no prior session must be able to call `initialize`
    then `tools/list` and get a non-empty tool list back, with no session-id
    header required (stateless_http=True) -- see AC13 / SOP §1.3 self-check.
    """

    app = build_app(no_call_expected_handler)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        TOKEN_HEADER: TOKEN,
    }

    async with run_lifespan(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            init_response = await http.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"},
                    },
                },
            )
            assert init_response.status_code == 200

            # No Mcp-Session-Id is sent back on this second call -- a session-id
            # requirement would surface as "400 Missing session ID" here.
            list_response = await http.post(
                "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
            )
    assert list_response.status_code == 200
    body = _parse_sse_json(list_response.text)
    tool_names = {tool["name"] for tool in body["result"]["tools"]}
    assert tool_names == EXPECTED_TOOL_NAMES
    assert len(tool_names) == 13


def _parse_sse_json(text: str) -> dict:
    """FastMCP's Streamable HTTP responses are text/event-stream; extract the
    JSON payload from the `data:` line."""

    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    raise AssertionError(f"no data: line found in SSE response: {text!r}")
