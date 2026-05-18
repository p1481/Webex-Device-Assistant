"""Prometheus ``/metrics`` exposition route."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from assistant_app.metrics import render_latest

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Return the current Prometheus exposition payload.

    Authentication is intentionally not enforced here — scraping is
    expected to be network-restricted (private subnet / ingress rule).
    If public exposure is required later, wrap this route with the
    admin auth dependency.
    """

    body, content_type = render_latest()
    return Response(content=body, media_type=content_type)
