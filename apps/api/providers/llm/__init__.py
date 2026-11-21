"""Provider-neutral LLM interface, event types and registry."""

from providers.llm.anthropic import AnthropicLLMProvider
from providers.llm.base import LLMProvider
from providers.llm.ollama import OllamaLLMProvider
from providers.llm.openai_compat import OpenAICompatibleLLMProvider
from providers.llm.registry import (
    available_providers,
    create_llm_provider,
    register_provider,
)
from providers.llm.types import (
    AuthenticationError,
    ChatMessage,
    Completion,
    ContextLengthError,
    Error,
    Finish,
    FinishReason,
    LLMEvent,
    LLMProviderError,
    Messages,
    ProviderAPIError,
    RateLimitError,
    TextDelta,
    UnknownProviderError,
    Usage,
)

__all__ = [
    "AnthropicLLMProvider",
    "AuthenticationError",
    "ChatMessage",
    "Completion",
    "ContextLengthError",
    "Error",
    "Finish",
    "FinishReason",
    "LLMEvent",
    "LLMProvider",
    "LLMProviderError",
    "Messages",
    "OllamaLLMProvider",
    "OpenAICompatibleLLMProvider",
    "ProviderAPIError",
    "RateLimitError",
    "TextDelta",
    "UnknownProviderError",
    "Usage",
    "available_providers",
    "create_llm_provider",
    "register_provider",
]
