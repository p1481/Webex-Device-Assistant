"""OpenTelemetry tracing setup for the assistant app.

Opt-in: tracing is **disabled by default** so test/dev environments without
an OTLP collector don't fail at startup. Enable by setting either:

- ``OTEL_ENABLED=true`` (preferred — explicit toggle), OR
- ``OTEL_SDK_DISABLED=false`` (standard OTel env)

Endpoint defaults to ``OTEL_EXPORTER_OTLP_ENDPOINT`` (standard env). When
unset, the OTLP exporter falls back to its library default
(``http://localhost:4317`` for gRPC).

Exports three helpers:

- :func:`configure_tracing(app)` — install SDK + auto-instrumentations.
- :func:`get_tracer(name)` — obtain a tracer for manual spans.
- :func:`traced(span_name)` — decorator that wraps an async method in a span.
  Becomes a near no-op when the SDK is disabled (OTel returns NoOpTracer).
"""

from __future__ import annotations

import functools
import logging
import os
from collections.abc import Callable
from typing import Any, TypeVar, cast

from opentelemetry import trace

logger = logging.getLogger(__name__)

_CONFIGURED = False

F = TypeVar("F", bound=Callable[..., Any])


def _enabled() -> bool:
    explicit = os.environ.get("OTEL_ENABLED", "").strip().lower()
    if explicit in {"1", "true", "yes", "on"}:
        return True
    if explicit in {"0", "false", "no", "off", ""}:
        # Fall through to OTEL_SDK_DISABLED — opt-in by default.
        pass
    sdk_disabled = os.environ.get("OTEL_SDK_DISABLED", "").strip().lower()
    return sdk_disabled in {"0", "false", "no", "off"}


def configure_tracing(app: Any | None = None) -> bool:
    """Initialize OTel SDK and auto-instrumentations.

    Returns True when tracing was activated, False when disabled or already
    configured. Safe to call multiple times.
    """

    global _CONFIGURED
    if _CONFIGURED:
        return False
    if not _enabled():
        logger.info(
            "tracing.disabled",
            extra={
                "hint": "Set OTEL_ENABLED=true to activate OpenTelemetry tracing",
            },
        )
        return False

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception as exc:  # pragma: no cover - defensive import guard
        logger.warning("tracing.import_failed", extra={"error": str(exc)})
        return False

    service_name = os.environ.get("OTEL_SERVICE_NAME", "webex-device-assistant")
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    try:
        exporter = OTLPSpanExporter()  # honours OTEL_EXPORTER_OTLP_ENDPOINT
        provider.add_span_processor(BatchSpanProcessor(exporter))
    except Exception as exc:  # pragma: no cover - exporter init errors
        logger.warning("tracing.exporter_init_failed", extra={"error": str(exc)})
        return False

    trace.set_tracer_provider(provider)

    # Auto-instrument FastAPI + httpx if available.
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        if app is not None:
            FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:  # pragma: no cover
        logger.warning("tracing.fastapi_instrument_failed", extra={"error": str(exc)})

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception as exc:  # pragma: no cover
        logger.warning("tracing.httpx_instrument_failed", extra={"error": str(exc)})

    _CONFIGURED = True
    logger.info("tracing.enabled", extra={"service_name": service_name})
    return True


def get_tracer(name: str) -> trace.Tracer:
    """Return a tracer; when tracing is disabled, OTel returns a no-op tracer."""

    return trace.get_tracer(name)


def traced(span_name: str, *, tracer_name: str = "assistant_app") -> Callable[[F], F]:
    """Decorate an async function so its execution becomes a span.

    Preserves the original callable's type (``F``) so callers continue to see
    a coroutine function rather than a generic ``Awaitable`` factory — this
    matters for ``Protocol`` matching (e.g. ``LLMProvider``).
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = trace.get_tracer(tracer_name)
            with tracer.start_as_current_span(span_name):
                return await func(*args, **kwargs)

        return cast(F, wrapper)

    return decorator


__all__ = ["configure_tracing", "get_tracer", "traced"]
