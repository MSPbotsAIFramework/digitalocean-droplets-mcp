"""Droplet action tools: digitalocean_droplet_action, digitalocean_list_droplet_actions,
digitalocean_get_action.

digitalocean_droplet_action consolidates 11 DigitalOcean "droplet action" endpoints
(they all share the same POST .../actions -> action-record shape) into one tool with
a `type` parameter, per SOP §2.1 ("tools are capabilities, not endpoint mirrors").
rebuild and change_kernel are intentionally left out of v1 (see design doc's Open
questions / Decisions) -- add them as additional SUPPORTED_ACTION_TYPES entries if a
future ticket asks for them; no new tool or contract change is needed for that.
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

SUPPORTED_ACTION_TYPES = (
    "power_on",
    "power_off",
    "power_cycle",
    "shutdown",
    "reboot",
    "resize",
    "rename",
    "snapshot",
    "restore",
    "enable_backups",
    "disable_backups",
    "enable_ipv6",
)

# Action types that take an extra required/optional argument beyond `type`.
_ACTION_EXTRA_FIELD = {
    "resize": "size",
    "rename": "name",
    "snapshot": "name",
    "restore": "image",
}


def _compact_action(action: dict) -> dict:
    return {
        "id": action.get("id"),
        "status": action.get("status"),
        "type": action.get("type"),
        "started_at": action.get("started_at"),
        "completed_at": action.get("completed_at"),
    }


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(
        description="Perform one lifecycle action on a Droplet (power, resize, rename, snapshot, restore, backups, ipv6).",
        annotations=ToolAnnotations(destructiveHint=True),
    )
    async def digitalocean_droplet_action(
        droplet_id: int,
        type: str,
        value: str | None = None,
    ) -> str:
        """Args: droplet_id (required). type (required, one of power_on, power_off,
        power_cycle, shutdown, reboot, resize, rename, snapshot, restore,
        enable_backups, disable_backups, enable_ipv6). value (required for
        resize/rename/snapshot/restore: the new size slug, the new name, the
        snapshot name, or the backup image id/slug respectively; ignored for all
        other types)."""

        if type not in SUPPORTED_ACTION_TYPES:
            return invalid_argument(
                f"Unsupported action type '{type}'. Supported: {', '.join(SUPPORTED_ACTION_TYPES)}"
            )

        extra_field = _ACTION_EXTRA_FIELD.get(type)
        if extra_field and not value:
            return invalid_argument(f"Action type '{type}' requires 'value' (the {extra_field})")

        client = client_factory()
        if client is None:
            return not_configured("No DigitalOcean credential available for this request")

        body: dict = {"type": type}
        if extra_field and value:
            body[extra_field] = value

        async with client:
            try:
                response = await client.request("POST", f"/droplets/{droplet_id}/actions", json_body=body)
            except UpstreamApiError as exc:
                return handle_upstream_error(exc)

        return json.dumps(_compact_action(response.get("action", {})), separators=(",", ":"), ensure_ascii=False)

    @mcp.tool(
        description="List the actions performed on one Droplet, most recent first.",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def digitalocean_list_droplet_actions(droplet_id: int, limit: int | None = None) -> str:
        """Args: droplet_id (required). limit (optional, default 50, max 200)."""

        client = client_factory()
        if client is None:
            return not_configured("No DigitalOcean credential available for this request")

        per_page = resolve_limit(limit)
        async with client:
            try:
                response = await client.request(
                    "GET", f"/droplets/{droplet_id}/actions", params={"per_page": per_page}
                )
            except UpstreamApiError as exc:
                return handle_upstream_error(exc)

        raw_actions = response.get("actions", [])
        return json.dumps(
            {
                "actions": [_compact_action(a) for a in raw_actions],
                "has_more": has_more(response, len(raw_actions), per_page),
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @mcp.tool(
        description="Get one action's current status by id. Use to poll a long-running action to completion.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    )
    async def digitalocean_get_action(action_id: int) -> str:
        """Args: action_id (required, the numeric action id returned by digitalocean_droplet_action)."""

        client = client_factory()
        if client is None:
            return not_configured("No DigitalOcean credential available for this request")

        async with client:
            try:
                response = await client.request("GET", f"/actions/{action_id}")
            except UpstreamApiError as exc:
                return handle_upstream_error(exc)

        return json.dumps(_compact_action(response.get("action", {})), separators=(",", ":"), ensure_ascii=False)
