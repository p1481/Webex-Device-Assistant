"""End-to-end and integration tests for the Device Assistant app.

Helpers and fixtures have been extracted to ``tests/_helpers.py`` and
``tests/conftest.py``. This file is being split by domain incrementally;
see ``docs/improvement-plan.md`` for the migration plan.
"""

from assistant_app.main import app
from tests._helpers import (
    build_authenticated_client,
)

client = build_authenticated_client(app)


def test_default_config_uses_ollama_for_llm_first_semantic_parsing() -> None:
    from assistant_app.config import AppConfig
    from assistant_app.ollama_support import DEFAULT_OLLAMA_BASE_URL, DEFAULT_OLLAMA_MODEL
    from shared.contracts import ProviderKind

    config = AppConfig.from_env()

    assert config.default_provider == ProviderKind.OLLAMA
    assert config.default_provider_model == DEFAULT_OLLAMA_MODEL
    assert config.default_provider_base_url == DEFAULT_OLLAMA_BASE_URL
