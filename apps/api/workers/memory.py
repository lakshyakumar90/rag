"""ARQ background job for consolidating chat turns into cognitive memories."""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from providers.embeddings import EmbeddingProvider
from providers.llm.base import LLMProvider
from services.memory import MemoryService

logger = logging.getLogger(__name__)

_FACT_CUE_RE = re.compile(
    r"\b(we deploy|we use|we migrated|our team|we switched|always|prefer|rule:)\b",
    re.I,
)


def extract_candidate_memories(
    user_text: str, assistant_text: str
) -> list[tuple[str, str]]:
    """Extract (tier, content) candidate memories from a completed chat turn."""
    candidates: list[tuple[str, str]] = []
    cleaned_user = user_text.strip()
    if cleaned_user and _FACT_CUE_RE.search(cleaned_user):
        tier = "procedural" if cleaned_user.lower().startswith("rule:") else "semantic"
        candidates.append((tier, cleaned_user[:500]))
    if len(cleaned_user) > 20 and len(assistant_text.strip()) > 30:
        summary = f"Q: {cleaned_user[:180]} | A: {assistant_text.strip()[:240]}"
        candidates.append(("episodic", summary))
    return candidates


async def consolidate_turn_memory(
    ctx: dict,
    workspace_id: str,
    user_id: str,
    conversation_id: str,
    user_text: str,
    assistant_text: str,
    llm: LLMProvider | None = None,
) -> int:
    """Extract candidate facts/summaries from a turn and reconcile into memory."""
    factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    embeddings: EmbeddingProvider | None = ctx.get("embedding_provider")
    candidates = extract_candidate_memories(user_text, assistant_text)
    if not candidates:
        return 0

    ws_id = uuid.UUID(workspace_id)
    uid = uuid.UUID(user_id)
    saved = 0
    async with factory() as session:
        service = MemoryService(session)
        for tier, content in candidates:
            vector: list[float] | None = None
            if embeddings is not None:
                try:
                    vector = await embeddings.embed_query(content)
                except Exception as exc:
                    logger.debug("Memory embedding skipped: %s", exc)
            _, created = await service.reconcile_candidate(
                ws_id,
                uid,
                content,
                tier=tier,
                embedding=vector,
                llm=llm,
            )
            if created is not None:
                saved += 1
    return saved
