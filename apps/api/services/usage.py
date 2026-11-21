"""Workspace usage, analytics and audit-log queries."""

import uuid
from collections import Counter
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AuditLog, Conversation, Document, Message, MessageFeedback
from schemas import (
    AnalyticsResponse,
    AuditEntryResponse,
    DocumentStat,
    QuestionStat,
    UsageResponse,
)


class UsageService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def usage(self, workspace_id: uuid.UUID) -> UsageResponse:
        queries = await self._scalar(
            select(func.count())
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.workspace_id == workspace_id, Message.role == "user")
        )
        assistant_query = (
            select(
                Message.id,
                Message.input_tokens,
                Message.output_tokens,
                Message.tokens_estimated,
            )
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.workspace_id == workspace_id,
                Message.role == "assistant",
            )
        )
        assistant_rows = (await self._session.execute(assistant_query)).all()
        answers = len(assistant_rows)
        tokens = sum((row[1] or 0) + (row[2] or 0) for row in assistant_rows)
        estimated = sum(1 for row in assistant_rows if row[3])
        storage = await self._scalar(
            select(func.coalesce(func.sum(Document.size), 0)).where(
                Document.workspace_id == workspace_id
            )
        )
        documents = await self._scalar(
            select(func.count()).where(Document.workspace_id == workspace_id)
        )
        feedback_rows = (
            (
                await self._session.execute(
                    select(MessageFeedback.vote)
                    .join(Message, Message.id == MessageFeedback.message_id)
                    .join(Conversation, Conversation.id == Message.conversation_id)
                    .where(Conversation.workspace_id == workspace_id)
                )
            )
            .scalars()
            .all()
        )
        votes = Counter(feedback_rows)
        return UsageResponse(
            workspace_id=workspace_id,
            queries=int(queries),
            answers=int(answers),
            input_tokens=0,  # kept separate in the token total for v1
            output_tokens=int(tokens),
            estimated_token_answers=int(estimated),
            documents=int(documents),
            storage_bytes=int(storage),
            feedback_up=votes.get("up", 0),
            feedback_down=votes.get("down", 0),
        )

    async def analytics(self, workspace_id: uuid.UUID) -> AnalyticsResponse:
        user_questions = (
            (
                await self._session.execute(
                    select(Message.content)
                    .join(Conversation, Conversation.id == Message.conversation_id)
                    .where(
                        Conversation.workspace_id == workspace_id,
                        Message.role == "user",
                    )
                )
            )
            .scalars()
            .all()
        )
        counts = Counter(
            " ".join(str(value).strip().lower().split()) for value in user_questions
        )
        most_asked = [
            QuestionStat(question=question, count=count)
            for question, count in counts.most_common(10)
            if question
        ]

        # Pair every low-confidence answer with the user question immediately
        # before it (by conversation + insertion sequence).
        user_turns = (
            await self._session.execute(
                select(Message.conversation_id, Message.sequence, Message.content)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Conversation.workspace_id == workspace_id,
                    Message.role == "user",
                )
                .order_by(Message.conversation_id, Message.sequence)
            )
        ).all()
        low_confidence_rows = (
            await self._session.execute(
                select(Message.conversation_id, Message.sequence)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Conversation.workspace_id == workspace_id,
                    Message.role == "assistant",
                    (Message.answerable.is_(False))
                    | (Message.content == "I don't know"),
                )
            )
        ).all()
        questions_by_conversation: dict[uuid.UUID, list[tuple[int, str]]] = {}
        for conversation_id, sequence, content in user_turns:
            questions_by_conversation.setdefault(conversation_id, []).append(
                (sequence, str(content))
            )
        low_confidence_counts: Counter[str] = Counter()
        for conversation_id, sequence in low_confidence_rows:
            preceding = [
                text
                for user_sequence, text in questions_by_conversation.get(
                    conversation_id, []
                )
                if user_sequence < sequence
            ]
            if preceding:
                normalized = " ".join(preceding[-1].strip().lower().split())
                if normalized:
                    low_confidence_counts[normalized] += 1
        low_confidence_questions = [
            QuestionStat(question=question, count=count)
            for question, count in low_confidence_counts.most_common(10)
        ]

        citations = (
            (
                await self._session.execute(
                    select(Message.citations)
                    .join(Conversation, Conversation.id == Message.conversation_id)
                    .where(
                        Conversation.workspace_id == workspace_id,
                        Message.role == "assistant",
                        Message.citations.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        document_counts: Counter[tuple[str | None, str]] = Counter()
        for rows in citations:
            if not isinstance(rows, list):
                continue
            for citation in rows:
                if not isinstance(citation, dict):
                    continue
                doc_id = citation.get("document_id")
                key = (
                    str(doc_id) if doc_id else None,
                    str(citation.get("filename") or "unknown"),
                )
                document_counts[key] += 1
        most_cited = [
            DocumentStat(
                document_id=uuid.UUID(key[0]) if key[0] else None,
                filename=key[1],
                citations=count,
            )
            for key, count in document_counts.most_common(10)
        ]
        return AnalyticsResponse(
            workspace_id=workspace_id,
            most_asked=most_asked,
            low_confidence_count=len(low_confidence_rows),
            low_confidence_questions=low_confidence_questions,
            most_cited=most_cited,
        )

    async def audit(
        self, workspace_id: uuid.UUID, limit: int = 100
    ) -> list[AuditEntryResponse]:
        result = await self._session.execute(
            select(AuditLog)
            .where(AuditLog.workspace_id == workspace_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
        )
        return [
            AuditEntryResponse.model_validate(entry) for entry in result.scalars().all()
        ]

    async def _scalar(self, statement) -> int:
        return cast(int, (await self._session.execute(statement)).scalar_one())
