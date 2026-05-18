"""Structured logging configuration for the assistant app.

Uses structlog to emit either pretty colored console logs (development) or
JSON logs (production), while keeping the stdlib ``logging`` API intact so
existing ``logging.getLogger(__name__)`` call sites work unchanged.

Context (request_id, session_id, etc.) bound via
``structlog.contextvars.bind_contextvars`` is automatically attached to every
log record produced during the scope of an asyncio task / request.

Activation: call :func:`configure_logging` once at startup. Idempotent —
safe to call multiple times (e.g. from tests).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

_CONFIGURED_FLAG = "_assistant_app_structlog_configured"


def _use_json_output() -> bool:
    """Return True when JSON logs are requested.

    Defaults to JSON in production-like environments (when stdout is not a
    TTY) and to colored console output during interactive development.
    Override explicitly with ``LOG_FORMAT=json`` or ``LOG_FORMAT=console``.
    """

    override = os.environ.get("LOG_FORMAT", "").strip().lower()
    if override == "json":
        return True
    if override == "console":
        return False
    return not sys.stdout.isatty()


def _log_level() -> int:
    raw = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    return logging.getLevelName(raw) if raw else logging.INFO  # type: ignore[return-value]


def _add_module_name(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """Surface stdlib logger name under the ``logger`` key for parity with
    the legacy ``%(name)s`` format string."""

    record = event_dict.get("_record")
    if isinstance(record, logging.LogRecord):
        event_dict.setdefault("logger", record.name)
    return event_dict


def _build_processors(json_output: bool) -> list[Processor]:
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_module_name,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if json_output:
        shared.append(structlog.processors.JSONRenderer())
    else:
        shared.append(structlog.dev.ConsoleRenderer(colors=True))
    return shared


def configure_logging() -> None:
    """Install structlog as the application logging backend.

    Idempotent: subsequent calls reuse the existing handler.
    """

    root_logger = logging.getLogger()
    if getattr(root_logger, _CONFIGURED_FLAG, False):
        return

    json_output = _use_json_output()
    level = _log_level()

    processors = _build_processors(json_output)

    # Configure structlog itself.
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging records through structlog's formatter so that
    # ``logging.getLogger(__name__)`` users get the same structured output.
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=(
            structlog.processors.JSONRenderer()
            if json_output
            else structlog.dev.ConsoleRenderer(colors=True)
        ),
        foreign_pre_chain=processors[:-1],
    )

    # Remove any previously installed handler we own; preserve foreign ones.
    for handler in list(root_logger.handlers):
        if getattr(handler, "_assistant_app_handler", False):
            root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(level)
    handler._assistant_app_handler = True  # type: ignore[attr-defined]
    root_logger.addHandler(handler)
    if root_logger.level == logging.WARNING or root_logger.level > level:
        root_logger.setLevel(level)

    for logger_name in (
        "assistant_app.main",
        "assistant_app.webex_gateway",
        "assistant_app.webhook_controller",
    ):
        logging.getLogger(logger_name).setLevel(level)

    root_logger._assistant_app_structlog_configured = True  # type: ignore[attr-defined]


def bind_request_context(**values: Any) -> None:
    """Attach key/value pairs to the current asyncio task's log context."""

    structlog.contextvars.bind_contextvars(**values)


def clear_request_context() -> None:
    """Clear the current task's log context (e.g. at request teardown)."""

    structlog.contextvars.clear_contextvars()


def get_logger(name: str | None = None) -> Any:
    """Return a structlog bound logger.

    Equivalent to ``structlog.get_logger(name)`` but exposed here so callers
    don't need to import structlog directly.
    """

    return structlog.get_logger(name)


__all__ = [
    "bind_request_context",
    "clear_request_context",
    "configure_logging",
    "get_logger",
]
