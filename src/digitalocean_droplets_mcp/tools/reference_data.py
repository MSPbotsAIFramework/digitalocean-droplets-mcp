"""Reference-data tools an agent needs before creating a Droplet:
digitalocean_list_regions, digitalocean_list_sizes, digitalocean_list_images.
"""

from __future__ import annotations

import json
from typing import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from digitalocean_droplets_mcp.client import DigitalOceanClient
from digitalocean_droplets_mcp.errors import UpstreamApiError, handle_upstream_error, invalid_argument, not_configured
from digitalocean_droplets_mcp.pagination import has_more, resolve_limit

ClientFactory = Callable[[], DigitalOceanClient | None]

SUPPORTED_IMAGE_TYPES = ("distribution", "application", "private")


def _compact_region(region: dict) -> dict:
    return {
        "slug": region.get("slug"),
        "name": region.get("name"),
        "available": region.get("available"),
        "sizes": region.get("sizes"),
    }


def _compact_size(size: dict) -> dict:
    return {
        "slug": size.get("slug"),
        "memory": size.get("memory"),
        "vcpus": size.get("vcpus"),
        "disk": size.get("disk"),
        "price_monthly": size.get("price_monthly"),
        "regions": size.get("regions"),
        "available": size.get("available"),
    }


def _compact_image(image: dict) -> dict:
    return {
        "id": image.get("id"),
        "slug": image.get("slug"),
        "name": image.get("name"),
        "distribution": image.get("distribution"),
        "type": image.get("type"),
        "regions": image.get("regions"),
    }


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(
        description="List DigitalOcean regions and their slugs, for use in digitalocean_create_droplet.",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def digitalocean_list_regions(limit: int | None = None) -> str:
        """Args: limit (optional, default 50, max 200)."""

        client = client_factory()
        if client is None:
            return not_configured("No DigitalOcean credential available for this request")

        per_page = resolve_limit(limit)
        async with client:
            try:
                response = await client.request(
                    "GET", "/regions", params={"per_page": per_page}, tool_name="digitalocean_list_regions"
                )
            except UpstreamApiError as exc:
                return handle_upstream_error(exc)

        raw_regions = response.get("regions", [])
        return json.dumps(
            {
                "regions": [_compact_region(r) for r in raw_regions],
                "has_more": has_more(response, len(raw_regions), per_page),
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @mcp.tool(
        description="List DigitalOcean Droplet sizes and their slugs, for use in digitalocean_create_droplet.",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def digitalocean_list_sizes(limit: int | None = None) -> str:
        """Args: limit (optional, default 50, max 200)."""

        client = client_factory()
        if client is None:
            return not_configured("No DigitalOcean credential available for this request")

        per_page = resolve_limit(limit)
        async with client:
            try:
                response = await client.request(
                    "GET", "/sizes", params={"per_page": per_page}, tool_name="digitalocean_list_sizes"
                )
            except UpstreamApiError as exc:
                return handle_upstream_error(exc)

        raw_sizes = response.get("sizes", [])
        return json.dumps(
            {
                "sizes": [_compact_size(s) for s in raw_sizes],
                "has_more": has_more(response, len(raw_sizes), per_page),
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @mcp.tool(
        description="List DigitalOcean images and their slugs/ids, for use in digitalocean_create_droplet.",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def digitalocean_list_images(type: str | None = None, limit: int | None = None) -> str:
        """Args: type (optional, one of distribution/application/private; omit for all).
        limit (optional, default 50, max 200)."""

        if type is not None and type not in SUPPORTED_IMAGE_TYPES:
            return invalid_argument(f"Unsupported type '{type}'. Supported: {', '.join(SUPPORTED_IMAGE_TYPES)}")

        client = client_factory()
        if client is None:
            return not_configured("No DigitalOcean credential available for this request")

        per_page = resolve_limit(limit)
        params: dict = {"per_page": per_page}
        if type:
            params["type"] = type

        async with client:
            try:
                response = await client.request(
                    "GET", "/images", params=params, tool_name="digitalocean_list_images"
                )
            except UpstreamApiError as exc:
                return handle_upstream_error(exc)

        raw_images = response.get("images", [])
        return json.dumps(
            {
                "images": [_compact_image(i) for i in raw_images],
                "has_more": has_more(response, len(raw_images), per_page),
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
