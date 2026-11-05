"""Structured (JSON) logging setup (SOP SS6).

One log record = one JSON line on stdout: level, logger name, message, plus
whatever non-sensitive fields the caller passes via `log_event`. Credentials,
the token value, and full request/response bodies must never be passed in --
callers pass only summary fields (tool name, status, duration, error code).

Stdlib `logging` is enough here: this service makes one outbound call per
tool call, so there is nothing a heavier logging library would buy over a
small formatter (YAGNI) -- consistent with the rest of this project only
taking on dependencies it actually needs (httpx, pydantic-settings, uvicorn).
"""

from __future__ import annotations

import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    """Renders each LogRecord as one JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(fields)
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    """Install the JSON formatter on the root logger. Idempotent -- build_app()
    may run more than once per process (every test module calls it)."""

    root = logging.getLogger()
    if any(isinstance(handler.formatter, JsonFormatter) for handler in root.handlers):
        root.setLevel(level)
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    root.setLevel(level)


def log_event(logger: logging.Logger, message: str, **fields: object) -> None:
    """Log one structured record. `fields` must already be non-sensitive --
    never pass a credential, token, or raw request/response body here."""

    logger.info(message, extra={"fields": fields})
