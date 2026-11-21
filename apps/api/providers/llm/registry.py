"""Provider registry and factory for chat-model backends."""

from collections.abc import Callable

from core.config import get_settings
from providers.llm.base import LLMProvider
from providers.llm.ollama import OllamaLLMProvider
from providers.llm.types import UnknownProviderError

ProviderFactory = Callable[..., LLMProvider]

_registry: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Register (or replace) a provider factory under ``name``."""
    _registry[name] = factory


def available_providers() -> list[str]:
    return sorted(_registry)


def create_llm_provider(name: str | None = None, **opts: object) -> LLMProvider:
    """Build a provider by name, defaulting to the configured ``llm_provider``."""
    key = name or get_settings().llm_provider
    try:
        factory = _registry[key]
    except KeyError as exc:
        raise UnknownProviderError(key) from exc
    return factory(**opts)


# Built-in providers.
register_provider("ollama", lambda **opts: OllamaLLMProvider(**opts))
