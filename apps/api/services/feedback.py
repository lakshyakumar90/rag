"""Message feedback (thumbs up/down with an optional comment)."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models import Message, MessageFeedback
from schemas import FeedbackRequest, FeedbackResponse
from services.exceptions import MessageNotFoundError
from services.workspaces import WorkspaceContext


class FeedbackService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set(
        self,
        context: WorkspaceContext,
        message_id: uuid.UUID,
        payload: FeedbackRequest,
    ) -> FeedbackResponse:
        await self._owned_message(context, message_id)
        result = await self._session.execute(
            select(MessageFeedback).where(
                MessageFeedback.message_id == message_id,
                MessageFeedback.user_id == context.user.id,
            )
        )
        feedback = result.scalar_one_or_none()
        if feedback is None:
            feedback = MessageFeedback(
                message_id=message_id,
                user_id=context.user.id,
                vote=payload.vote,
                comment=payload.comment,
            )
            self._session.add(feedback)
        else:
            feedback.vote = payload.vote
            feedback.comment = payload.comment
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MessageNotFoundError() from exc
        await self._session.refresh(feedback)
        return FeedbackResponse(
            message_id=feedback.message_id,
            vote=feedback.vote,
            comment=feedback.comment,
            created_at=feedback.created_at,
        )

    async def _owned_message(
        self, context: WorkspaceContext, message_id: uuid.UUID
    ) -> Message:
        from models import Conversation

        result = await self._session.execute(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == message_id,
                Message.role == "assistant",
                Conversation.workspace_id == context.workspace.id,
            )
        )
        message = result.scalar_one_or_none()
        if message is None:
            raise MessageNotFoundError()
        return message
