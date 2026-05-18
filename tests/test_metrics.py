"""Tests for the Prometheus ``/metrics`` exposition endpoint."""

from __future__ import annotations

from assistant_app import metrics as metrics_module
from assistant_app.main import app
from tests._helpers import build_unauthenticated_client


def test_metrics_endpoint_exposes_prometheus_payload() -> None:
    client = build_unauthenticated_client(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    content_type = response.headers["content-type"]
    # prometheus_client uses 'text/plain; version=0.0.4; charset=utf-8'
    assert content_type.startswith("text/plain")
    body = response.text
    # Core metric families should be present (HELP lines emitted even
    # when no samples have been recorded yet).
    assert "assistant_requests_total" in body
    assert "assistant_request_duration_seconds" in body
    assert "device_xapi_calls_total" in body
    assert "device_xapi_duration_seconds" in body
    assert "provider_analyze_duration_seconds" in body
    assert "approvals_pending" in body


def test_render_latest_returns_bytes_and_content_type() -> None:
    body, content_type = metrics_module.render_latest()
    assert isinstance(body, bytes)
    assert content_type == metrics_module.CONTENT_TYPE_LATEST


def test_observe_duration_records_sample() -> None:
    hist = metrics_module.provider_analyze_duration_seconds
    before = hist.labels(provider="UnitTestProvider")._sum.get()  # type: ignore[attr-defined]
    with metrics_module.observe_duration(hist, provider="UnitTestProvider"):
        pass
    after = hist.labels(provider="UnitTestProvider")._sum.get()  # type: ignore[attr-defined]
    assert after >= before


def test_set_request_labels_round_trips() -> None:
    metrics_module.set_request_labels(intent="control_call", mode="auto")
    intent, mode = metrics_module.get_request_labels()
    assert intent == "control_call"
    assert mode == "auto"


def test_set_request_labels_partial_update() -> None:
    metrics_module.set_request_labels(intent="chat", mode="manual")
    metrics_module.set_request_labels(intent="reset_context")
    intent, mode = metrics_module.get_request_labels()
    assert intent == "reset_context"
    assert mode == "manual"
