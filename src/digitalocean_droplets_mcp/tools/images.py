"""Snapshot and backup tools: digitalocean_list_snapshots, digitalocean_delete_snapshot,
digitalocean_list_backups.
"""

from __future__ import annotations

import json
from typing import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from digitalocean_droplets_mcp.client import DigitalOceanClient
from digitalocean_droplets_mcp.errors import UpstreamApiError, handle_upstream_error, not_configured
from digitalocean_droplets_mcp.pagination import has_more, resolve_limit

ClientFactory = Callable[[], DigitalOceanClient | None]


def _compact_snapshot(snapshot: dict) -> dict:
    return {
        "id": snapshot.get("id"),
        "name": snapshot.get("name"),
        "created_at": snapshot.get("created_at"),
        "regions": snapshot.get("regions"),
        "min_disk_size": snapshot.get("min_disk_size"),
    }


def _compact_backup(backup: dict) -> dict:
    return {
        "id": backup.get("id"),
        "name": backup.get("name"),
        "created_at": backup.get("created_at"),
        "min_disk_size": backup.get("min_disk_size"),
    }


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(
        description="List the snapshots taken of one Droplet.",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def digitalocean_list_snapshots(droplet_id: int, limit: int | None = None) -> str:
        """Args: droplet_id (required). limit (optional, default 50, max 200)."""

        client = client_factory()
        if client is None:
            return not_configured("No DigitalOcean credential available for this request")

        per_page = resolve_limit(limit)
        async with client:
            try:
                response = await client.request(
                    "GET",
                    f"/droplets/{droplet_id}/snapshots",
                    params={"per_page": per_page},
                    tool_name="digitalocean_list_snapshots",
                )
            except UpstreamApiError as exc:
                return handle_upstream_error(exc)

        raw_snapshots = response.get("snapshots", [])
        return json.dumps(
            {
                "snapshots": [_compact_snapshot(s) for s in raw_snapshots],
                "has_more": has_more(response, len(raw_snapshots), per_page),
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @mcp.tool(
        description="Destroy exactly one Droplet snapshot by id. No bulk delete.",
        annotations=ToolAnnotations(destructiveHint=True),
    )
    async def digitalocean_delete_snapshot(snapshot_id: int) -> str:
        """Args: snapshot_id (required, the numeric snapshot id to destroy)."""

        client = client_factory()
        if client is None:
            return not_configured("No DigitalOcean credential available for this request")

        async with client:
            try:
                await client.request(
                    "DELETE", f"/snapshots/{snapshot_id}", tool_name="digitalocean_delete_snapshot"
                )
            except UpstreamApiError as exc:
                return handle_upstream_error(exc)

        return json.dumps({"id": snapshot_id, "deleted": True}, separators=(",", ":"), ensure_ascii=False)

    @mcp.tool(
        description="List the automatic backups taken of one Droplet.",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def digitalocean_list_backups(droplet_id: int, limit: int | None = None) -> str:
        """Args: droplet_id (required). limit (optional, default 50, max 200)."""

        client = client_factory()
        if client is None:
            return not_configured("No DigitalOcean credential available for this request")

        per_page = resolve_limit(limit)
        async with client:
            try:
                response = await client.request(
                    "GET",
                    f"/droplets/{droplet_id}/backups",
                    params={"per_page": per_page},
                    tool_name="digitalocean_list_backups",
                )
            except UpstreamApiError as exc:
                return handle_upstream_error(exc)

        raw_backups = response.get("backups", [])
        return json.dumps(
            {
                "backups": [_compact_backup(b) for b in raw_backups],
                "has_more": has_more(response, len(raw_backups), per_page),
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
