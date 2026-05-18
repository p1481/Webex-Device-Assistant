"""Prometheus metrics for the assistant app.

Defines the core counters / histograms / gauges enumerated in the
observability plan and exposes lightweight helpers so call sites stay
declarative.

The actual `/metrics` HTTP endpoint lives in
:mod:`assistant_app.routes.metrics` to keep route wiring separate from
metric definitions.

All metric names follow Prometheus conventions:
- ``*_total`` for monotonic counters
- ``*_seconds`` for time histograms (base unit: seconds)
- bare nouns for gauges

Labels are kept low-cardinality on purpose — avoid free-form text. Pass
``"unknown"`` rather than user input when a label value is missing.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Use the default global registry so prometheus_client's process_collector
# /platform_collector also flow through `/metrics`. A custom registry would
# work too, but the global default is more idiomatic.

# --- Counters -----------------------------------------------------------

assistant_requests_total: Final = Counter(
    "assistant_requests_total",
    "Total number of orchestrator requests processed.",
    labelnames=("intent", "mode", "outcome"),
)

device_xapi_calls_total: Final = Counter(
    "device_xapi_calls_total",
    "Total number of Webex device xAPI invocations.",
    labelnames=("endpoint", "status"),
)

# --- Histograms ---------------------------------------------------------

assistant_request_duration_seconds: Final = Histogram(
    "assistant_request_duration_seconds",
    "Wall-clock duration of orchestrator request handling in seconds.",
    labelnames=("intent",),
)

device_xapi_duration_seconds: Final = Histogram(
    "device_xapi_duration_seconds",
    "Wall-clock duration of Webex device xAPI calls in seconds.",
    labelnames=("endpoint",),
)

provider_analyze_duration_seconds: Final = Histogram(
    "provider_analyze_duration_seconds",
    "Wall-clock duration of provider.analyze_message in seconds.",
    labelnames=("provider",),
)

# --- Gauges -------------------------------------------------------------

approvals_pending: Final = Gauge(
    "approvals_pending",
    "Number of approval requests currently awaiting user response.",
)


# --- Per-request labels (ContextVar) ------------------------------------

_request_intent: ContextVar[str] = ContextVar("_request_intent", default="unknown")
_request_mode: ContextVar[str] = ContextVar("_request_mode", default="unknown")


def set_request_labels(*, intent: str | None = None, mode: str | None = None) -> None:
    """Record the resolved intent / execution mode for the in-flight request.

    The orchestrator calls this once the LLM decision (or fast-path
    handler) has determined the actual intent. The values flow to the
    ``assistant_requests_total`` counter and
    ``assistant_request_duration_seconds`` histogram when the request
    completes.

    Safe to call multiple times — the latest value wins. Async-safe via
    :class:`contextvars.ContextVar`.
    """

    if intent is not None:
        _request_intent.set(intent)
    if mode is not None:
        _request_mode.set(mode)


def get_request_labels() -> tuple[str, str]:
    """Return the current ``(intent, mode)`` labels for this request."""

    return _request_intent.get(), _request_mode.get()


# --- Helpers ------------------------------------------------------------


@contextmanager
def observe_duration(histogram: Histogram, **labels: str) -> Iterator[None]:
    """Context manager that records elapsed seconds into a labeled histogram.

    Example::

        with observe_duration(provider_analyze_duration_seconds, provider="ollama"):
            await provider.analyze_message(...)
    """

    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        if labels:
            histogram.labels(**labels).observe(elapsed)
        else:
            histogram.observe(elapsed)


def render_latest(registry: CollectorRegistry | None = None) -> tuple[bytes, str]:
    """Render the current Prometheus exposition payload.

    Returns ``(body, content_type)`` suitable for an HTTP response.
    """

    body = generate_latest(registry) if registry is not None else generate_latest()
    return body, CONTENT_TYPE_LATEST


__all__ = [
    "CONTENT_TYPE_LATEST",
    "approvals_pending",
    "assistant_request_duration_seconds",
    "assistant_requests_total",
    "device_xapi_calls_total",
    "device_xapi_duration_seconds",
    "get_request_labels",
    "observe_duration",
    "provider_analyze_duration_seconds",
    "render_latest",
    "set_request_labels",
]
