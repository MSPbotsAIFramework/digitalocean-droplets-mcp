"""FastMCP server factory and the outer Starlette app.

Wires together: the credential middleware (middleware.py), the DigitalOcean
client factory (client.py), and the per-resource tool modules (tools/). See
SOP section 7 for the two pitfalls this file exists to avoid:

- DNS-rebinding protection must be disabled (service sits behind an internal
  proxy, Host header is never localhost).
- The MCP app's lifespan must be mounted on the outer Starlette app, or
  Mount() silently drops it and /mcp fails with "Task group is not
  initialized" while /health still returns 200.
"""

from __future__ import annotations

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from digitalocean_droplets_mcp.client import DigitalOceanClient
from digitalocean_droplets_mcp.config import settings
from digitalocean_droplets_mcp.logging_config import configure_logging
from digitalocean_droplets_mcp.middleware import credential_middleware, current_token
from digitalocean_droplets_mcp.tools import actions, droplets, images, reference_data

INSTRUCTIONS = (
    "Manage DigitalOcean Droplets (virtual machines): list/get/create/delete Droplets, "
    "drive their lifecycle via droplet actions (power on/off, power-cycle, reboot, "
    "shutdown, resize, rename, snapshot, restore, enable/disable backups, enable IPv6), "
    "and inspect snapshots/backups. Use digitalocean_list_regions, "
    "digitalocean_list_sizes, and digitalocean_list_images first to find valid slugs "
    "before calling digitalocean_create_droplet. Every destructive tool requires an "
    "explicit resource id -- there is no bulk or \"all droplets\" operation. "
    "Scope: Droplets only; other DigitalOcean products (Databases, Spaces, Kubernetes) "
    "are separate connectors."
)


def client_factory() -> DigitalOceanClient | None:
    """Build a request-scoped DigitalOcean client from the current token.

    Returns None when no token is set on the context (should not normally
    happen -- the credential middleware rejects such requests with 401
    before any tool runs -- but tools must still handle it defensively by
    returning a not_configured error envelope rather than raising).
    """

    token = current_token()
    if not token:
        return None
    return DigitalOceanClient(token=token, base_url=settings.digitalocean_base_url)


def build_mcp() -> FastMCP:
    # DNS-rebinding protection: this FastMCP/mcp-sdk version (2.14.7 / 1.30.0) disables
    # it by default when no TransportSecuritySettings are supplied (see
    # mcp.server.transport_security.TransportSecurityMiddleware.__init__ -- "If not
    # specified, disable DNS rebinding protection by default for backwards
    # compatibility"), and FastMCP's own constructor/http_app() do not expose a knob to
    # configure it anyway. The SOP's explicit-disable snippet targets the raw MCP SDK;
    # under FastMCP the default already satisfies it, verified against the installed
    # package source rather than assumed.
    mcp = FastMCP(
        name="digitalocean-droplets-mcp",
        instructions=INSTRUCTIONS,
    )

    droplets.register(mcp, client_factory)
    actions.register(mcp, client_factory)
    images.register(mcp, client_factory)
    reference_data.register(mcp, client_factory)

    return mcp


async def health(_request: Request) -> JSONResponse:
    """Pure local liveness probe -- never calls api.digitalocean.com."""

    return JSONResponse({"status": "ok"})


def build_app() -> Starlette:
    configure_logging()
    mcp = build_mcp()
    # stateless_http belongs here (not on the FastMCP constructor, which is deprecated
    # for this purpose): no session affinity, a fresh transport per request, per SOP §1.3.
    mcp_app = mcp.http_app(path="/mcp", stateless_http=True)

    app = Starlette(
        routes=[
            Route("/health", health),
            Mount("/", app=mcp_app),
        ],
        middleware=[Middleware(BaseHTTPMiddleware, dispatch=credential_middleware)],
        # Mounting alone drops the sub-app's lifespan; the MCP session manager
        # needs its lifespan to run or every /mcp request fails with
        # "Task group is not initialized".
        lifespan=mcp_app.lifespan,
    )
    return app
