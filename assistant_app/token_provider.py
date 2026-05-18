from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

import httpx


class WebexTokenProvider(Protocol):
    async def get_bearer_token(self) -> str: ...


@dataclass(frozen=True, slots=True)
class TokenManagerTokenProvider:
    base_url: str
    api_key: str
    fallback_token: str | None = None
    current_token_path: str = "/api/tokens/current"
    timeout_seconds: float = 10.0

    async def get_bearer_token(self) -> str:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds
            ) as client:
                response = await client.get(
                    self.current_token_path,
                    headers={"x-api-key": self.api_key},
                )
                _ = response.raise_for_status()

            payload = cast(object, response.json())
            if not isinstance(payload, dict):
                raise RuntimeError("Unexpected token manager response shape.")

            payload_dict = cast(dict[str, object], payload)
            token = payload_dict.get("accessToken")
            if not isinstance(token, str) or not token.strip():
                raise RuntimeError("Token manager response did not include accessToken.")
            return token.strip()
        except Exception as exc:
            if isinstance(self.fallback_token, str) and self.fallback_token.strip():
                return self.fallback_token.strip()
            raise RuntimeError(
                "Failed to retrieve a Webex access token from the token manager. "
                "Check the token service health or configure WEBEX_BOT_TOKEN fallback."
            ) from exc
