"""Shared test helpers: build an MCP server (or full Starlette app) wired to a
mocked DigitalOcean API transport, so no test hits the real network.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable

import httpx
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.types import ASGIApp

from digitalocean_droplets_mcp import server
from digitalocean_droplets_mcp.client import DigitalOceanClient
from digitalocean_droplets_mcp.middleware import current_token
from digitalocean_droplets_mcp.tools import actions, droplets, images, reference_data

MOCK_BASE_URL = "https://api.digitalocean.com/v2"
DEFAULT_TEST_TOKEN = "test-token-value"

Handler = Callable[[httpx.Request], httpx.Response]


def client_factory_with_fixed_token(
    transport: httpx.MockTransport, token: str
) -> Callable[[], DigitalOceanClient | None]:
    """A client_factory() for in-process tool tests (fastmcp.Client), which never go
    through the real HTTP credential middleware -- so there is no contextvar to read.
    Used by build_mcp(); talks to a mocked DigitalOcean API instead of the real network.
    """

    def factory() -> DigitalOceanClient | None:
        return DigitalOceanClient(token=token, base_url=MOCK_BASE_URL, transport=transport)

    return factory


def client_factory_from_request_context(
    transport: httpx.MockTransport,
) -> Callable[[], DigitalOceanClient | None]:
    """A client_factory() that reads the real request-scoped token set by the production
    credential middleware. Used by build_app() so HTTP-level tests exercise the real
    header -> contextvar -> client wiring, with only the DigitalOcean network call mocked.
    """

    def factory() -> DigitalOceanClient | None:
        token = current_token()
        if not token:
            return None
        return DigitalOceanClient(token=token, base_url=MOCK_BASE_URL, transport=transport)

    return factory


def build_mcp(handler: Handler, token: str = DEFAULT_TEST_TOKEN) -> FastMCP:
    """A fresh FastMCP instance with all 13 tools registered against a mocked transport."""

    transport = httpx.MockTransport(handler)
    factory = client_factory_with_fixed_token(transport, token)

    mcp = FastMCP(name="digitalocean-droplets-mcp-test", instructions=server.INSTRUCTIONS)
    droplets.register(mcp, factory)
    actions.register(mcp, factory)
    images.register(mcp, factory)
    reference_data.register(mcp, factory)
    return mcp


def build_app(handler: Handler) -> Starlette:
    """The real Starlette app (middleware + /health + /mcp), with tool calls
    routed to a mocked DigitalOcean transport instead of the real network."""

    transport = httpx.MockTransport(handler)
    server.client_factory = client_factory_from_request_context(transport)  # type: ignore[assignment]
    return server.build_app()


@contextlib.asynccontextmanager
async def run_lifespan(app: ASGIApp) -> AsyncIterator[None]:
    """Drive the ASGI lifespan protocol by hand around a test.

    httpx.ASGITransport (unlike uvicorn) never sends lifespan.startup/shutdown
    events, and FastMCP's StreamableHTTPSessionManager needs its lifespan to run
    or every /mcp request fails with "Task group is not initialized" (SOP §7's
    documented pitfall) -- /health still returns 200 either way, which is exactly
    why that failure mode is easy to miss outside a lifespan-aware test harness.
    """

    to_app: asyncio.Queue = asyncio.Queue()
    from_app: asyncio.Queue = asyncio.Queue()

    async def receive() -> dict:
        return await to_app.get()

    async def send(message: dict) -> None:
        await from_app.put(message)

    task = asyncio.create_task(app({"type": "lifespan"}, receive, send))
    await to_app.put({"type": "lifespan.startup"})
    startup_result = await from_app.get()
    assert startup_result["type"] == "lifespan.startup.complete", startup_result

    try:
        yield
    finally:
        await to_app.put({"type": "lifespan.shutdown"})
        shutdown_result = await from_app.get()
        assert shutdown_result["type"] == "lifespan.shutdown.complete", shutdown_result
        await task


def no_call_expected_handler(_request: httpx.Request) -> httpx.Response:
    """A transport that fails the test if the tool ever reaches the DigitalOcean API --
    used for cases that must be rejected locally (missing header, invalid argument)."""

    raise AssertionError("DigitalOcean API must not be called for this case")
