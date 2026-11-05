"""Droplet CRUD tools: digitalocean_list_droplets, digitalocean_get_droplet,
digitalocean_create_droplet, digitalocean_delete_droplet.
"""

from __future__ import annotations

import json
from typing import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from digitalocean_droplets_mcp.client import DigitalOceanClient
from digitalocean_droplets_mcp.errors import (
    UpstreamApiError,
    handle_upstream_error,
    invalid_argument,
    not_configured,
)
from digitalocean_droplets_mcp.pagination import has_more, resolve_limit

ClientFactory = Callable[[], DigitalOceanClient | None]

REQUIRED_CREATE_FIELDS = ("name", "region", "size", "image")


def _compact_droplet(droplet: dict) -> dict:
    """Trim a DigitalOcean droplet record to the fields agents need (§2.5 token economy)."""

    region = droplet.get("region") or {}
    size = droplet.get("size") or {}
    image = droplet.get("image") or {}
    return {
        "id": droplet.get("id"),
        "name": droplet.get("name"),
        "status": droplet.get("status"),
        "region": region.get("slug", region) if isinstance(region, dict) else region,
        "size": droplet.get("size_slug") or (size.get("slug") if isinstance(size, dict) else size),
        "image": image.get("slug") or image.get("id") if isinstance(image, dict) else image,
        "networks": droplet.get("networks"),
    }


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(
        description="List Droplets on the account. Supports an optional tag_name filter.",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def digitalocean_list_droplets(
        tag_name: str | None = None, limit: int | None = None
    ) -> str:
        """Args: tag_name (optional, filter by tag), limit (optional, default 50, max 200)."""

        client = client_factory()
        if client is None:
            return not_configured("No DigitalOcean credential available for this request")

        per_page = resolve_limit(limit)
        params: dict = {"per_page": per_page}
        if tag_name:
            params["tag_name"] = tag_name

        async with client:
            try:
                response = await client.request(
                    "GET", "/droplets", params=params, tool_name="digitalocean_list_droplets"
                )
            except UpstreamApiError as exc:
                return handle_upstream_error(exc)

        raw_droplets = response.get("droplets", [])
        droplets = [_compact_droplet(d) for d in raw_droplets]
        return json.dumps(
            {"droplets": droplets, "has_more": has_more(response, len(raw_droplets), per_page)},
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @mcp.tool(
        description="Get the full record for one Droplet by id.",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def digitalocean_get_droplet(droplet_id: int) -> str:
        """Args: droplet_id (required, the numeric Droplet id)."""

        client = client_factory()
        if client is None:
            return not_configured("No DigitalOcean credential available for this request")

        async with client:
            try:
                response = await client.request(
                    "GET", f"/droplets/{droplet_id}", tool_name="digitalocean_get_droplet"
                )
            except UpstreamApiError as exc:
                return handle_upstream_error(exc)

        droplet = response.get("droplet", {})
        return json.dumps(_compact_droplet(droplet), separators=(",", ":"), ensure_ascii=False)

    @mcp.tool(
        description="Create a new Droplet. Use digitalocean_list_regions/sizes/images first to find valid slugs.",
    )
    async def digitalocean_create_droplet(
        name: str,
        region: str,
        size: str,
        image: str,
        ssh_keys: list[str] | None = None,
        backups: bool = False,
        ipv6: bool = False,
        tags: list[str] | None = None,
    ) -> str:
        """Args: name, region (slug), size (slug), image (slug or numeric id) are
        required. ssh_keys, backups, ipv6, tags are optional."""

        client = client_factory()
        if client is None:
            return not_configured("No DigitalOcean credential available for this request")

        body = {"name": name, "region": region, "size": size, "image": image}
        missing = [field for field in REQUIRED_CREATE_FIELDS if not body.get(field)]
        if missing:
            return invalid_argument(f"Missing required field(s): {', '.join(missing)}")

        if ssh_keys:
            body["ssh_keys"] = ssh_keys
        body["backups"] = backups
        body["ipv6"] = ipv6
        if tags:
            body["tags"] = tags

        async with client:
            try:
                response = await client.request(
                    "POST", "/droplets", json_body=body, tool_name="digitalocean_create_droplet"
                )
            except UpstreamApiError as exc:
                return handle_upstream_error(exc)

        droplet = response.get("droplet", {})
        return json.dumps(
            {"id": droplet.get("id"), "name": droplet.get("name"), "status": droplet.get("status")},
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @mcp.tool(
        description="Destroy exactly one Droplet by id. No bulk or \"all droplets\" delete exists.",
        annotations=ToolAnnotations(destructiveHint=True),
    )
    async def digitalocean_delete_droplet(droplet_id: int) -> str:
        """Args: droplet_id (required, the numeric Droplet id to destroy)."""

        client = client_factory()
        if client is None:
            return not_configured("No DigitalOcean credential available for this request")

        async with client:
            try:
                await client.request(
                    "DELETE", f"/droplets/{droplet_id}", tool_name="digitalocean_delete_droplet"
                )
            except UpstreamApiError as exc:
                return handle_upstream_error(exc)

        return json.dumps({"id": droplet_id, "deleted": True}, separators=(",", ":"), ensure_ascii=False)
