"""Entry point: start the HTTP server."""

from __future__ import annotations

import uvicorn

from digitalocean_droplets_mcp.config import settings
from digitalocean_droplets_mcp.server import build_app


def main() -> None:
    app = build_app()
    uvicorn.run(app, host=settings.mcp_http_host, port=settings.mcp_http_port)


if __name__ == "__main__":
    main()
