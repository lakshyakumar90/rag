"""Conversation lifecycle, query rewriting, history truncation and titles."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from models import Conversation, Message
from providers.llm.base import LLMProvider
from providers.llm.registry import create_llm_provider
from providers.llm.types import ChatMessage
from repositories import ConversationRepository
from schemas import ConversationResponse, MessageResponse
from services.exceptions import ConversationNotFoundError
from services.workspaces import WorkspaceContext
from workers.tokenization import count_tokens

_REWRITE_SYSTEM = (
    "Rewrite the user's final question as a standalone question that can be "
    "understood without the conversation history. Reply with only the question."
)
_TITLE_SYSTEM = (
    "Write a short title (at most six words) for the user's question. "
    "Reply with only the title, without quotes."
)
_FALLBACK_TITLE = "New conversation"


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._conversations = ConversationRepository(session)

    async def create(
        self,
        context: WorkspaceContext,
        title: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> ConversationResponse:
        conversation = Conversation(
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            title=(title or "").strip()[:200] or _FALLBACK_TITLE,
            provider=provider or None,
            model=model or None,
        )
        await self._conversations.add(conversation)
        await self._session.commit()
        return ConversationResponse.model_validate(conversation)

    async def set_selection(
        self,
        context: WorkspaceContext,
        conversation_id: uuid.UUID,
        provider: str | None,
        model: str | None,
    ) -> ConversationResponse:
        """Persist a per-conversation provider/model override."""
        conversation = await self.get(context, conversation_id)
        conversation.provider = provider or None
        conversation.model = model or None
        await self._session.commit()
        await self._session.refresh(conversation)
        return ConversationResponse.model_validate(conversation)

    async def list_for_user(
        self, context: WorkspaceContext
    ) -> list[ConversationResponse]:
        conversations = await self._conversations.list_for_user(
            context.workspace.id, context.user.id
        )
        return [ConversationResponse.model_validate(item) for item in conversations]

    async def get(
        self, context: WorkspaceContext, conversation_id: uuid.UUID
    ) -> Conversation:
        conversation = await self._conversations.get(
            context.workspace.id, context.user.id, conversation_id
        )
        if conversation is None:
            raise ConversationNotFoundError()
        return conversation

    async def messages(
        self, context: WorkspaceContext, conversation_id: uuid.UUID
    ) -> list[MessageResponse]:
        await self.get(context, conversation_id)
        messages = await self._conversations.list_messages(conversation_id)
        return [MessageResponse.model_validate(message) for message in messages]

    async def delete(
        self, context: WorkspaceContext, conversation_id: uuid.UUID
    ) -> None:
        conversation = await self.get(context, conversation_id)
        await self._conversations.delete(conversation)
        await self._session.commit()

    async def add_message(
        self,
        conversation_id: uuid.UUID,
        *,
        role: str,
        content: str,
        citations: list | None = None,
        provider: str | None = None,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        tokens_estimated: bool = False,
        answerable: bool | None = None,
        confidence_score: float | None = None,
        confidence_level: str | None = None,
        confidence_breakdown: dict | None = None,
        retrieval_diagnostics: dict | None = None,
        commit: bool = True,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            citations=citations,
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            confidence_breakdown=confidence_breakdown,
            retrieval_diagnostics=retrieval_diagnostics,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            tokens_estimated=tokens_estimated,
            answerable=answerable,
        )
        await self._conversations.add_message(message)
        if commit:
            await self._session.commit()
        return message

    async def commit(self) -> None:
        await self._session.commit()

    async def rename(
        self, context: WorkspaceContext, conversation_id: uuid.UUID, title: str
    ) -> ConversationResponse:
        conversation = await self.get(context, conversation_id)
        conversation.title = title.strip()[:200] or "New conversation"
        await self._session.commit()
        await self._session.refresh(conversation)
        return ConversationResponse.model_validate(conversation)

    async def delete_last_turn(self, conversation_id: uuid.UUID) -> None:
        """Remove the last assistant message and its user question."""
        result = await self._session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sequence.desc())
            .limit(2)
        )
        for message in result.scalars().all():
            await self._session.delete(message)
        await self._session.flush()

    # ---------- prompting helpers ----------

    @staticmethod
    def truncate_history(messages: list, budget: int | None = None) -> list:
        """Keep the newest messages that fit the token budget."""
        budget = budget or get_settings().chat_history_token_budget
        kept: list = []
        used = 0
        for message in reversed(messages):
            cost = count_tokens(message.content)
            if kept and used + cost > budget:
                break
            kept.append(message)
            used += cost
        return list(reversed(kept))

    async def rewrite_query(
        self, history: list, query: str, provider: LLMProvider
    ) -> str:
        """Resolve pronouns/references in a follow-up using recent history."""
        settings = get_settings()
        if not history or not settings.chat_rewrite_enabled:
            return query
        recent = self.truncate_history(history)
        transcript = "\n".join(
            f"{message.role}: {message.content}" for message in recent
        )
        try:
            completion = await provider.complete(
                [
                    ChatMessage(role="system", content=_REWRITE_SYSTEM),
                    ChatMessage(
                        role="user",
                        content=f"{transcript}\n\nFinal question: {query}",
                    ),
                ],
                max_tokens=128,
            )
        except Exception:
            return query
        rewritten = completion.text.strip().strip('"')
        return rewritten or query

    async def generate_title(self, query: str, provider: LLMProvider) -> str:
        """Create a short conversation title from the first user message."""
        if not get_settings().chat_title_enabled:
            return query.strip()[:60] or _FALLBACK_TITLE
        try:
            completion = await provider.complete(
                [
                    ChatMessage(role="system", content=_TITLE_SYSTEM),
                    ChatMessage(role="user", content=query),
                ],
                max_tokens=32,
            )
        except Exception:
            return query.strip()[:60] or _FALLBACK_TITLE
        title = completion.text.strip().strip('"').splitlines()[0]
        return title[:200] or query.strip()[:60] or _FALLBACK_TITLE

    @staticmethod
    def provider_for(name: str) -> LLMProvider:
        return create_llm_provider(name)
