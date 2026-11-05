# PRD-21341 · Code review

## Round 2 · 2026-11-05 · reviewed dev/PRD-21341 @ aac0213 (base main @ 7099212)

Status: frozen @ aac0213

Verdict: approved

### Fixes (round 1 must-fix items)

1. `client.py:70-93` — retry loop now wrapped in `asyncio.wait_for(..., timeout=OVERALL_BUDGET_SECONDS)` with `OVERALL_BUDGET_SECONDS = 100.0`, and the timeout/network-error branch only calls `self._backoff()` `if attempt < MAX_RETRIES` (matching the existing 429/5xx branch), so it no longer sleeps after the final attempt. Verified: `tests/test_client.py::test_timeout_retries_exactly_max_retries_times_with_backoff_only_between_attempts` (4 attempts, exactly 3 backoff calls `[0, 1, 2]`) and `::test_overall_budget_aborts_a_permanently_stalled_upstream_well_under_120s` (budget shrunk to 0.3s via monkeypatch, call aborts in well under 5s instead of the ~135-240s worst case). Commit `db332ba`.
2. `client.py`, `tools/*.py`, `middleware.py`, `server.py` — structured JSON logging added: new `logging_config.py` (`JsonFormatter`, `configure_logging()`, `log_event()`), a request-correlation id in `middleware.py` (`current_request_id()`, set/reset alongside the token var, never logged), and `client.py::_log()` logging `request_id`, `tool_name`, `method`, `path`, `status_code`, `duration_ms`, `attempts`, `digitalocean_request_id`, `error_code` — never the token or response bodies. All 13 tool call sites now pass `tool_name=`. Verified: `tests/test_client.py::test_call_is_logged_with_tool_status_duration_and_never_the_token` asserts the fields are present and that `SECRET_TOKEN` never appears in any log record. Commit `db332ba`.

### Verification this round

- `git diff 398cdac..aac0213`: only `client.py`, `errors.py` (extracted `error_code_for_status()` to share the status→code mapping, no behavior change), `logging_config.py` (new), `middleware.py`, `server.py`, `tools/*.py` (mechanical `tool_name=` passthrough), `tests/test_client.py` (3 new regression tests), and the two doc files. No change outside the two must-fix items' scope.
- `uv sync && uv run pytest -q`: 22 passed, 0 failed (on `aac0213`, synced with `main @ 7099212` — still an ancestor, no merge needed).
- Chinese-text scan (`grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .`): only pre-existing hits inside this review record's own round-1 finding text (quoting the SOP); no hits in any source/doc file this round touched.
- README Connector section: unchanged this round, still byte-identical to `reference/readme-connector-section.md` (verified in round 1).
- Token/credential handling: `_token_var` contextvar, reset in `finally`, never passed to `log_event`; grep for `token` across `src/` confirms the only places it reaches are the `Authorization` header construction and the context var itself.

## Round 1 · 2026-11-05 · reviewed dev/PRD-21341 @ 398cdac (base main @ 7099212)

Verdict: changes requested

### Findings

1. [must-fix] src/digitalocean_droplets_mcp/client.py:70-93 — the retry/backoff loop has no overall deadline, so a single tool call can exceed the SOP's mandatory "single call total time (including retries) must be < 120s" budget (`vendor-mcp-development-sop.md` §5, checklist §14 "错误与网络"). `DigitalOceanClient.request` runs up to `MAX_RETRIES + 1 = 4` attempts with `READ_TIMEOUT = 30.0`s per attempt; on `httpx.TimeoutException`/`httpx.HTTPError` (client.py:73-79) it unconditionally calls `self._backoff(attempt)` on every attempt including the last one (no `attempt < MAX_RETRIES` guard on that branch, unlike the 429/5xx branch at client.py:92), adding up to 4 backoff sleeps instead of 3. Worst case against a slow/timing-out upstream: 4 × 30s request timeouts + 4 backoff sleeps (exponential 1/2/4/8s without `Retry-After`, or up to 30s each when a `Retry-After` is present) ≈ 135-240s, well past the mandated 120s. Fix: wrap the whole retry loop in an overall deadline (e.g. `asyncio.wait_for` or a running total compared against a 120s budget) that stops retrying and returns `upstream_error` once the budget is spent, and only back off on the exception branches when another attempt will actually be made (`attempt < MAX_RETRIES`).
2. [must-fix] src/digitalocean_droplets_mcp/client.py, tools/*.py, middleware.py, server.py — no structured logging exists anywhere in the implementation (`grep -rn "logging\|logger" src/` returns nothing), but the tech design's Non-functional section explicitly commits to it: "Observability: structured logs on every tool call (`tool name`, `status`, `duration_ms`, DigitalOcean request id when present) — never the token value" (docs/tickets/PRD-21341.md:156), and the SOP mandates it unconditionally: "一个逐请求处理多租户凭据的 HTTP 服务，日志必须谨慎... 用结构化日志...记录：工具名、入参摘要（脱敏）、你的 API 路径与状态码、耗时、错误 code" (`vendor-mcp-development-sop.md` §6) and checklist §14 "结构化日志带 request-id；不打印凭据/token/敏感业务数据". Without any logging, a production incident (rate limiting, upstream errors, credential issues) leaves no operational trail to diagnose from, and the shipped code does not match what the design and Self-test sections claim was built. Fix: add structured logging (tool name, status, duration_ms, DigitalOcean request id when present, error code) in client.py/tools, with the token value and full request/response bodies never logged.
