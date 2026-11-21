"""Provider-neutral LLM interface, event types and registry."""

from providers.llm.base import LLMProvider
from providers.llm.ollama import OllamaLLMProvider
from providers.llm.registry import (
    available_providers,
    create_llm_provider,
    register_provider,
)
from providers.llm.types import (
    ChatMessage,
    Completion,
    Error,
    Finish,
    FinishReason,
    LLMEvent,
    LLMProviderError,
    Messages,
    TextDelta,
    UnknownProviderError,
    Usage,
)

__all__ = [
    "ChatMessage",
    "Completion",
    "Error",
    "Finish",
    "FinishReason",
    "LLMEvent",
    "LLMProvider",
    "LLMProviderError",
    "Messages",
    "OllamaLLMProvider",
    "TextDelta",
    "UnknownProviderError",
    "Usage",
    "available_providers",
    "create_llm_provider",
    "register_provider",
]
