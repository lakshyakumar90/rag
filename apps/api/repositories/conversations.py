"""Data access for conversations and messages (workspace/user scoped)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Conversation, Message


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[Conversation]:
        result = await self._session.execute(
            select(Conversation)
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.user_id == user_id,
            )
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
        )
        return list(result.scalars().all())

    async def get(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> Conversation | None:
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.workspace_id == workspace_id,
                Conversation.user_id == user_id,
                Conversation.id == conversation_id,
            )
        )
        return result.scalar_one_or_none()

    async def add(self, conversation: Conversation) -> Conversation:
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def delete(self, conversation: Conversation) -> None:
        await self._session.delete(conversation)
        await self._session.flush()

    async def list_messages(self, conversation_id: uuid.UUID) -> list[Message]:
        result = await self._session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sequence, Message.id)
        )
        return list(result.scalars().all())

    async def add_message(self, message: Message) -> Message:
        result = await self._session.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == message.conversation_id)
        )
        message.sequence = int(result.scalar_one())
        self._session.add(message)
        await self._session.flush()
        return message
