"""Provider-neutral message and stream-event types for chat models."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant"]
FinishReason = Literal["stop", "length", "content_filter", "other"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class TextDelta:
    """A fragment of assistant text, emitted in order during streaming."""

    text: str


@dataclass(frozen=True)
class Finish:
    reason: FinishReason


@dataclass(frozen=True)
class Error:
    message: str
    code: str | None = None


@dataclass(frozen=True)
class Completion:
    """Result of a non-streaming completion."""

    text: str
    finish_reason: FinishReason
    usage: Usage = field(default_factory=Usage)


LLMEvent = TextDelta | Usage | Finish | Error


class LLMProviderError(Exception):
    """Base error for provider wiring and runtime failures."""


class ProviderAPIError(LLMProviderError):
    """A provider rejected the request."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        retry_after: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after


class AuthenticationError(ProviderAPIError):
    """Missing, invalid, or unauthorized credentials."""


class RateLimitError(ProviderAPIError):
    """The provider rate limit was hit."""


class ContextLengthError(ProviderAPIError):
    """The prompt (or prompt + completion) exceeds the model's context window."""


class UnknownProviderError(LLMProviderError):
    """No provider is registered under the requested name."""

    def __init__(self, name: str) -> None:
        super().__init__(f"unknown LLM provider: {name}")
        self.name = name


# Options are passed as **opts so providers can add their own knobs; these are
# the widely supported ones that the Ollama provider maps explicitly.
CompletionOptions = dict[str, Any]
Messages = Sequence[ChatMessage]
