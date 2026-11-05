"""Unit tests for DigitalOceanClient.request's retry/backoff/deadline behavior
(PRD-21341 code review round 1, must-fix #1) and its structured call log
(must-fix #2): the overall retry loop must never be able to push a single tool
call past the SOP's <120s budget, a backoff sleep must only happen when another
attempt will actually follow, and every call must log tool name/status/duration
without ever logging the credential.
"""

from __future__ import annotations

import logging
import time

import httpx
import pytest

import digitalocean_droplets_mcp.client as client_module
from conftest import MOCK_BASE_URL
from digitalocean_droplets_mcp.client import MAX_RETRIES, DigitalOceanClient
from digitalocean_droplets_mcp.errors import UpstreamApiError

SECRET_TOKEN = "do_v1_super_secret_token_value"


async def test_timeout_retries_exactly_max_retries_times_with_backoff_only_between_attempts(monkeypatch):
    """Regression for the round-1 bug: the timeout/network-error branch used to call
    _backoff() unconditionally, including after the final attempt (3 retries should
    mean 3 backoff sleeps between the 4 attempts, never a 4th sleep with nothing
    left to wait for)."""

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("simulated stall", request=request)

    transport = httpx.MockTransport(handler)
    client = DigitalOceanClient(token="t", base_url=MOCK_BASE_URL, transport=transport)

    backoff_calls: list[int] = []

    async def fake_backoff(attempt: int, retry_after: str | None = None) -> None:
        backoff_calls.append(attempt)

    monkeypatch.setattr(DigitalOceanClient, "_backoff", staticmethod(fake_backoff))

    async with client:
        with pytest.raises(UpstreamApiError) as exc_info:
            await client.request("GET", "/droplets/1", tool_name="digitalocean_get_droplet")

    assert call_count == MAX_RETRIES + 1
    assert backoff_calls == [0, 1, 2]  # one less than the number of attempts -- never after the last
    assert exc_info.value.status_code == 0
    assert exc_info.value.attempts == MAX_RETRIES + 1


async def test_overall_budget_aborts_a_permanently_stalled_upstream_well_under_120s(monkeypatch):
    """Regression for the round-1 bug: a slow/timing-out upstream must not be able
    to push a single call past the SOP's mandatory <120s budget. Shrinks the budget
    so the test runs fast instead of waiting the real 100s."""

    monkeypatch.setattr(client_module, "OVERALL_BUDGET_SECONDS", 0.3)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated permanent stall", request=request)

    transport = httpx.MockTransport(handler)
    client = DigitalOceanClient(token="t", base_url=MOCK_BASE_URL, transport=transport)

    start = time.monotonic()
    async with client:
        with pytest.raises(UpstreamApiError) as exc_info:
            await client.request("GET", "/droplets/1", tool_name="digitalocean_get_droplet")
    elapsed = time.monotonic() - start

    assert exc_info.value.status_code == 0
    assert "retry budget" in exc_info.value.message
    # Generous margin over the 0.3s budget for scheduler jitter -- still proves
    # asyncio.wait_for cut the call short instead of running all 4 attempts'
    # worth of READ_TIMEOUT + backoff (which would take tens of seconds).
    assert elapsed < 5.0


async def test_call_is_logged_with_tool_status_duration_and_never_the_token(caplog):
    """Regression for the round-1 bug: no structured logging existed anywhere.
    Every call must log at least tool_name/status_code/duration_ms/attempts, and
    must never log the credential value (SOP SS6/SS11)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"droplet": {"id": 1}}, headers={"x-request-id": "do-req-abc"})

    transport = httpx.MockTransport(handler)
    client = DigitalOceanClient(token=SECRET_TOKEN, base_url=MOCK_BASE_URL, transport=transport)

    with caplog.at_level(logging.INFO, logger="digitalocean_droplets_mcp.client"):
        async with client:
            await client.request("GET", "/droplets/1", tool_name="digitalocean_get_droplet")

    call_records = [r for r in caplog.records if r.name == "digitalocean_droplets_mcp.client"]
    assert len(call_records) == 1
    fields = call_records[0].fields  # set via logging_config.log_event's `extra={"fields": ...}`
    assert fields["tool_name"] == "digitalocean_get_droplet"
    assert fields["status_code"] == 200
    assert fields["attempts"] == 1
    assert isinstance(fields["duration_ms"], float)
    assert fields["digitalocean_request_id"] == "do-req-abc"

    for record in caplog.records:
        assert SECRET_TOKEN not in record.getMessage()
        assert SECRET_TOKEN not in str(getattr(record, "fields", {}))
