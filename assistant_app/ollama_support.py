from __future__ import annotations

import httpx

from shared.contracts import ProviderSettings

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434/api"
DEFAULT_OLLAMA_MODEL = "gemma4:latest"


async def check_ollama_availability(
    settings: ProviderSettings,
) -> tuple[bool, str | None]:
    base_url = settings.base_url or DEFAULT_OLLAMA_BASE_URL
    model = settings.model or DEFAULT_OLLAMA_MODEL
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
            response = await client.get("/tags")
            response.raise_for_status()
    except httpx.HTTPError as exc:
        return False, f"Ollama is unreachable at {base_url}: {exc}"

    payload: object = response.json()
    if not isinstance(payload, dict):
        return False, "Unexpected Ollama tags response shape."

    models = payload.get("models")
    if not isinstance(models, list):
        return False, "Unexpected Ollama tags response shape."

    available_models = {
        item.get("name")
        for item in models
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if model not in available_models:
        return False, f"Ollama model {model!r} is not installed."

    return True, None
