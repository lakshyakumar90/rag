"""4-tier cognitive memory service with conflict resolution and superseding."""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.memory import WorkspaceMemory
from providers.llm.base import LLMProvider
from providers.llm.types import ChatMessage
from repositories.retrieval import _cosine

logger = logging.getLogger(__name__)

_MIGRATION_CUES = (
    "migrated",
    "moved",
    "switched",
    "changed",
    "updated",
    "now ",
    "replaced",
)
_REGION_RE = re.compile(r"\b[a-z]{2}-[a-z]+-\d\b", re.I)


@dataclass(frozen=True)
class ReconcileDecision:
    action: str  # ADD | UPDATE | NOOP | INVALIDATE
    target_id: uuid.UUID | None = None
    content: str | None = None
    reason: str = ""


def _parse_json(raw: str) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def _token_set(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_-]{3,}", text.lower())}


class MemoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_memories(
        self,
        workspace_id: uuid.UUID,
        *,
        tier: str | None = None,
        include_superseded: bool = False,
    ) -> list[WorkspaceMemory]:
        conditions = [WorkspaceMemory.workspace_id == workspace_id]
        if tier:
            conditions.append(WorkspaceMemory.tier == tier)
        if not include_superseded:
            conditions.append(WorkspaceMemory.status == "active")
        stmt = (
            select(WorkspaceMemory)
            .where(*conditions)
            .order_by(WorkspaceMemory.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def create_memory(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID | None,
        tier: str,
        content: str,
        *,
        confidence: float = 0.9,
        embedding: list[float] | None = None,
    ) -> WorkspaceMemory:
        mem = WorkspaceMemory(
            workspace_id=workspace_id,
            user_id=user_id,
            tier=tier,
            content=content.strip(),
            status="active",
            confidence=confidence,
            embedding=embedding,
        )
        self._session.add(mem)
        await self._session.commit()
        await self._session.refresh(mem)
        return mem

    async def update_memory(
        self,
        workspace_id: uuid.UUID,
        memory_id: uuid.UUID,
        *,
        content: str | None = None,
        status: str | None = None,
        confidence: float | None = None,
    ) -> WorkspaceMemory | None:
        mem = (
            await self._session.execute(
                select(WorkspaceMemory).where(
                    WorkspaceMemory.id == memory_id,
                    WorkspaceMemory.workspace_id == workspace_id,
                )
            )
        ).scalar_one_or_none()
        if mem is None:
            return None
        if content is not None:
            mem.content = content.strip()
        if status is not None:
            mem.status = status
        if confidence is not None:
            mem.confidence = confidence
        await self._session.commit()
        await self._session.refresh(mem)
        return mem

    async def delete_memory(
        self, workspace_id: uuid.UUID, memory_id: uuid.UUID
    ) -> bool:
        mem = (
            await self._session.execute(
                select(WorkspaceMemory).where(
                    WorkspaceMemory.id == memory_id,
                    WorkspaceMemory.workspace_id == workspace_id,
                )
            )
        ).scalar_one_or_none()
        if mem is None:
            return False
        await self._session.delete(mem)
        await self._session.commit()
        return True

    async def retrieve_for_prompt(
        self,
        workspace_id: uuid.UUID,
        query_vector: list[float] | None = None,
        top_k: int = 5,
    ) -> tuple[list[WorkspaceMemory], list[WorkspaceMemory]]:
        """Return (top_k_semantic_and_episodic, all_active_procedural_rules)."""
        active = await self.list_memories(workspace_id, include_superseded=False)
        procedural = [m for m in active if m.tier == "procedural"]
        candidates = [m for m in active if m.tier in ("semantic", "episodic")]

        if query_vector and candidates:
            scored = []
            for mem in candidates:
                sim = (
                    _cosine(query_vector, mem.embedding or []) if mem.embedding else 0.0
                )
                scored.append((sim, mem))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            selected = [mem for sim, mem in scored[:top_k] if sim > 0.0] or [
                mem for _, mem in scored[:top_k]
            ]
        else:
            selected = candidates[:top_k]
        return selected, procedural

    async def reconcile_candidate(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID | None,
        candidate_content: str,
        *,
        tier: str = "semantic",
        embedding: list[float] | None = None,
        llm: LLMProvider | None = None,
    ) -> tuple[ReconcileDecision, WorkspaceMemory | None]:
        """Reconcile a candidate memory against active memories."""
        candidate = candidate_content.strip()
        if not candidate:
            return ReconcileDecision(action="NOOP", reason="Empty candidate"), None

        existing = await self.list_memories(
            workspace_id, tier=tier, include_superseded=False
        )
        # Find semantically similar existing memories
        neighbors: list[tuple[float, WorkspaceMemory]] = []
        cand_tokens = _token_set(candidate)
        for mem in existing:
            if embedding and mem.embedding:
                sim = _cosine(embedding, mem.embedding)
            else:
                mem_tokens = _token_set(mem.content)
                union = cand_tokens | mem_tokens
                sim = (len(cand_tokens & mem_tokens) / len(union)) if union else 0.0
            if sim >= 0.15 or (
                _REGION_RE.search(candidate) and _REGION_RE.search(mem.content)
            ):
                neighbors.append((sim, mem))
        neighbors.sort(key=lambda pair: pair[0], reverse=True)
        top_neighbors = [mem for _, mem in neighbors[:5]]

        decision = await self._decide(candidate, top_neighbors, llm)

        if decision.action == "NOOP":
            return decision, None

        if decision.action == "INVALIDATE" and decision.target_id is not None:
            target = next(
                (m for m in top_neighbors if m.id == decision.target_id), None
            )
            if target is not None:
                target.status = "superseded"
                await self._session.commit()
            return decision, None

        new_mem = WorkspaceMemory(
            workspace_id=workspace_id,
            user_id=user_id,
            tier=tier,
            content=(decision.content or candidate).strip(),
            status="active",
            confidence=0.9,
            embedding=embedding,
        )
        self._session.add(new_mem)
        await self._session.flush()

        if decision.action == "UPDATE" and decision.target_id is not None:
            target = next(
                (m for m in top_neighbors if m.id == decision.target_id), None
            )
            if target is not None:
                target.status = "superseded"
                target.superseded_by_id = new_mem.id

        await self._session.commit()
        await self._session.refresh(new_mem)
        return decision, new_mem

    async def _decide(
        self,
        candidate: str,
        neighbors: list[WorkspaceMemory],
        llm: LLMProvider | None,
    ) -> ReconcileDecision:
        if not neighbors:
            return ReconcileDecision(
                action="ADD", content=candidate, reason="No prior match"
            )

        if llm is not None:
            existing_lines = "\n".join(f"- id={m.id}: {m.content}" for m in neighbors)
            prompt = (
                "You are a memory conflict reconciler.\n"
                "Compare NEW_FACT against EXISTING_MEMORIES and decide ONE action:\n"
                "- ADD: genuinely new non-contradictory fact\n"
                "- UPDATE: supersedes an existing memory (set target_id)\n"
                "- NOOP: already captured identically\n"
                "- INVALIDATE: retracts an existing memory (set target_id)\n"
                'Return STRICT JSON ONLY: {"action": "ADD|UPDATE|NOOP|INVALIDATE", '
                '"target_id": "<uuid or null>", "content": "<consolidated fact>", '
                '"reason": "..."}.\n\n'
                f"EXISTING_MEMORIES:\n{existing_lines}\n\nNEW_FACT: {candidate}"
            )
            try:
                resp = await llm.complete(
                    [ChatMessage(role="user", content=prompt)],
                    max_tokens=256,
                    temperature=0.0,
                )
                data = _parse_json(resp.text)
                action = str(data.get("action", "ADD")).upper()
                raw_tid = data.get("target_id")
                tid = uuid.UUID(str(raw_tid)) if raw_tid else None
                return ReconcileDecision(
                    action=action
                    if action in ("ADD", "UPDATE", "NOOP", "INVALIDATE")
                    else "ADD",
                    target_id=tid,
                    content=data.get("content") or candidate,
                    reason=str(data.get("reason") or ""),
                )
            except Exception as exc:
                logger.warning("Memory reconciler LLM fallback: %s", exc)

        # Deterministic heuristic fallback for conflict / duplicate detection
        cand_norm = " ".join(candidate.lower().split())
        cand_lower = candidate.lower()
        cand_regions = set(_REGION_RE.findall(cand_lower))
        has_migration_cue = any(cue in cand_lower for cue in _MIGRATION_CUES)

        for mem in neighbors:
            mem_norm = " ".join(mem.content.lower().split())
            if cand_norm == mem_norm:
                return ReconcileDecision(
                    action="NOOP", target_id=mem.id, reason="Duplicate memory"
                )
            mem_regions = set(_REGION_RE.findall(mem.content.lower()))
            if cand_regions and mem_regions and cand_regions != mem_regions:
                return ReconcileDecision(
                    action="UPDATE",
                    target_id=mem.id,
                    content=candidate,
                    reason="Supersedes prior region/deployment fact",
                )
            if has_migration_cue:
                return ReconcileDecision(
                    action="UPDATE",
                    target_id=mem.id,
                    content=candidate,
                    reason="Supersedes prior fact via migration/update cue",
                )

        return ReconcileDecision(
            action="ADD", content=candidate, reason="Distinct fact"
        )
