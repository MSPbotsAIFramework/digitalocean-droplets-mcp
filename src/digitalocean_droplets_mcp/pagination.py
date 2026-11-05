"""Shared limit/has_more pagination helper for every list tool.

Not part of the public tool contract (see tech design's Data & API contract
section) -- an internal implementation detail reused across tools/*.py
tools so the limit/has_more rule is enforced identically everywhere instead
of being reimplemented per tool.
"""

from __future__ import annotations

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def resolve_limit(limit: int | None) -> int:
    """Clamp a caller-supplied limit into [1, MAX_LIMIT], defaulting to DEFAULT_LIMIT."""

    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1:
        return 1
    if limit > MAX_LIMIT:
        return MAX_LIMIT
    return limit


def has_more(response: dict, returned_count: int, per_page: int) -> bool:
    """True when DigitalOcean's `links.pages.next` indicates another page exists."""

    if returned_count < per_page:
        return False
    links = response.get("links") or {}
    pages = links.get("pages") or {}
    return "next" in pages
