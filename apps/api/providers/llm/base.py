"""The provider contract shared by all chat-model backends."""

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from providers.llm.types import Completion, LLMEvent, Messages


@runtime_checkable
class LLMProvider(Protocol):
    """Normalized chat interface: streaming events or a single completion."""

    name: str

    def stream(self, messages: Messages, **opts: Any) -> AsyncIterator[LLMEvent]: ...

    async def complete(self, messages: Messages, **opts: Any) -> Completion: ...
