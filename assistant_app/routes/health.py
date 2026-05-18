"""Health-check route."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, str]:
    config = request.app.state.services.config
    return {
        "status": "ok",
        "default_execution_mode": config.default_execution_mode.value,
        "webex_mock_mode": str(config.webex_mock_mode).lower(),
        "device_mock_mode": str(config.device_mock_mode).lower(),
    }
