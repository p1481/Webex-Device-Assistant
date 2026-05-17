from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from assistant_app.ollama_support import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
)
from shared.contracts import ExecutionMode, ProviderKind


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_mode(name: str, default: ExecutionMode) -> ExecutionMode:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower().replace("_", "-")
    return ExecutionMode(normalized)


def _env_text(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _require_env(name: str, value: str | None) -> None:
    if value is None:
        raise ValueError(f"{name} is required when WEBEX_MOCK_MODE=false.")


def _require_env_for_mode(name: str, value: str | None, mode_name: str) -> None:
    if value is None:
        raise ValueError(f"{name} is required when {mode_name}=false.")


def _validate_https_url(name: str, value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{name} must be a valid https URL.")


def _require_literal(name: str, value: str, expected: str) -> None:
    if value != expected:
        raise ValueError(f"{name} must be {expected!r}.")


@dataclass(slots=True)
class AppConfig:
    app_name: str = "Webex Device Assistant App"
    admin_state_path: str | None = None
    default_provider: ProviderKind = ProviderKind.OLLAMA
    default_provider_model: str = DEFAULT_OLLAMA_MODEL
    default_provider_base_url: str | None = DEFAULT_OLLAMA_BASE_URL
    webex_api_base: str = "https://webexapis.com/v1"
    webex_bot_token: str | None = None
    webex_bot_person_id: str | None = None
    webex_webhook_secret: str | None = None
    webex_webhook_target_url: str | None = None
    webex_token_manager_base_url: str = "http://127.0.0.1:3000"
    webex_token_manager_api_key: str | None = None
    webex_webhook_name: str = "webex-device-assistant-messages-created"
    webex_webhook_direct_name: str = "webex-device-assistant-messages-created-direct"
    webex_webhook_group_name: str = (
        "webex-device-assistant-messages-created-group-mention"
    )
    webex_webhook_resource: str = "messages"
    webex_webhook_event: str = "created"
    webex_webhook_filter: str | None = None
    webex_webhook_reconcile_on_startup: bool = False
    webex_mock_mode: bool = True
    device_mock_mode: bool = True
    admin_cookie_secret: str | None = None
    default_execution_mode: ExecutionMode = ExecutionMode.SEPARATED
    default_target_device: str = ""

    def validate(self) -> AppConfig:
        if self.webex_mock_mode:
            return self._validate_device_config()

        _require_env("WEBEX_BOT_TOKEN", self.webex_bot_token)
        _require_env("WEBEX_BOT_PERSON_ID", self.webex_bot_person_id)
        _require_env("WEBEX_WEBHOOK_SECRET", self.webex_webhook_secret)
        _require_env("ADMIN_COOKIE_SECRET", self.admin_cookie_secret)
        _require_literal(
            "WEBEX_WEBHOOK_RESOURCE", self.webex_webhook_resource, "messages"
        )
        _require_literal("WEBEX_WEBHOOK_EVENT", self.webex_webhook_event, "created")

        if self.webex_webhook_target_url is not None:
            _validate_https_url(
                "WEBEX_WEBHOOK_TARGET_URL", self.webex_webhook_target_url
            )

        if self.webex_webhook_reconcile_on_startup:
            _require_env("WEBEX_WEBHOOK_TARGET_URL", self.webex_webhook_target_url)

        return self._validate_device_config()

    def _validate_device_config(self) -> AppConfig:
        if self.device_mock_mode:
            return self

        _require_env_for_mode(
            "WEBEX_TOKEN_MANAGER_BASE_URL",
            self.webex_token_manager_base_url,
            "DEVICE_MOCK_MODE",
        )
        _require_env_for_mode(
            "WEBEX_TOKEN_MANAGER_API_KEY",
            self.webex_token_manager_api_key,
            "DEVICE_MOCK_MODE",
        )
        return self

    @classmethod
    def from_env(cls) -> AppConfig:
        config = cls(
            admin_state_path=_env_text("ADMIN_STATE_PATH"),
            default_provider=ProviderKind(
                os.getenv("DEFAULT_PROVIDER", ProviderKind.OLLAMA.value)
            ),
            default_provider_model=os.getenv(
                "DEFAULT_PROVIDER_MODEL",
                DEFAULT_OLLAMA_MODEL
                if os.getenv("DEFAULT_PROVIDER", ProviderKind.OLLAMA.value)
                == ProviderKind.OLLAMA.value
                else "rule-based-default",
            ),
            default_provider_base_url=_env_text("DEFAULT_PROVIDER_BASE_URL"),
            webex_api_base=os.getenv("WEBEX_API_BASE", "https://webexapis.com/v1"),
            webex_bot_token=_env_text("WEBEX_BOT_TOKEN"),
            webex_bot_person_id=_env_text("WEBEX_BOT_PERSON_ID"),
            webex_webhook_secret=_env_text("WEBEX_WEBHOOK_SECRET"),
            webex_webhook_target_url=_env_text("WEBEX_WEBHOOK_TARGET_URL"),
            webex_token_manager_base_url=os.getenv(
                "WEBEX_TOKEN_MANAGER_BASE_URL", "http://127.0.0.1:3000"
            ),
            webex_token_manager_api_key=_env_text("WEBEX_TOKEN_MANAGER_API_KEY"),
            webex_webhook_name=os.getenv(
                "WEBEX_WEBHOOK_NAME", "webex-device-assistant-messages-created"
            ),
            webex_webhook_direct_name=os.getenv(
                "WEBEX_WEBHOOK_DIRECT_NAME",
                "webex-device-assistant-messages-created-direct",
            ),
            webex_webhook_group_name=os.getenv(
                "WEBEX_WEBHOOK_GROUP_NAME",
                "webex-device-assistant-messages-created-group-mention",
            ),
            webex_webhook_resource=os.getenv("WEBEX_WEBHOOK_RESOURCE", "messages"),
            webex_webhook_event=os.getenv("WEBEX_WEBHOOK_EVENT", "created"),
            webex_webhook_filter=_env_text("WEBEX_WEBHOOK_FILTER"),
            webex_webhook_reconcile_on_startup=_env_flag(
                "WEBEX_WEBHOOK_RECONCILE_ON_STARTUP", False
            ),
            webex_mock_mode=_env_flag("WEBEX_MOCK_MODE", True),
            device_mock_mode=_env_flag("DEVICE_MOCK_MODE", True),
            admin_cookie_secret=_env_text("ADMIN_COOKIE_SECRET"),
            default_execution_mode=_env_mode(
                "DEFAULT_EXECUTION_MODE", ExecutionMode.SEPARATED
            ),
            default_target_device=os.getenv("DEFAULT_TARGET_DEVICE", ""),
        )
        if config.default_provider == ProviderKind.OLLAMA:
            config.default_provider_base_url = (
                config.default_provider_base_url or DEFAULT_OLLAMA_BASE_URL
            )
        return config.validate()
