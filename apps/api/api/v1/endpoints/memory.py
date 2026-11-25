"""REST CRUD endpoints for 4-tier workspace cognitive memories."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.dependencies import MemberContext, get_embedding_provider
from core.database import get_session
from providers.embeddings import EmbeddingProvider
from schemas.memory import MemoryCreate, MemoryResponse, MemoryTier, MemoryUpdate
from services.memory import MemoryService

router = APIRouter(prefix="/workspaces/{workspace_id}/memories", tags=["memory"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
EmbeddingsDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]


@router.get("", response_model=list[MemoryResponse])
async def list_memories(
    context: MemberContext,
    session: SessionDep,
    tier: Annotated[MemoryTier | None, Query()] = None,
    include_superseded: Annotated[bool, Query()] = False,
) -> list[MemoryResponse]:
    service = MemoryService(session)
    items = await service.list_memories(
        context.workspace.id, tier=tier, include_superseded=include_superseded
    )
    return [MemoryResponse.model_validate(item) for item in items]


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryCreate,
    context: MemberContext,
    session: SessionDep,
    embeddings: EmbeddingsDep,
) -> MemoryResponse:
    service = MemoryService(session)
    vector: list[float] | None = None
    try:
        vector = await embeddings.embed_query(payload.content)
    except Exception:
        vector = None
    if payload.tier == "procedural":
        mem = await service.create_memory(
            context.workspace.id,
            context.user.id,
            payload.tier,
            payload.content,
            confidence=payload.confidence,
            embedding=vector,
        )
    else:
        _, mem = await service.reconcile_candidate(
            context.workspace.id,
            context.user.id,
            payload.content,
            tier=payload.tier,
            embedding=vector,
        )
        if mem is None:
            # NOOP duplicate: return latest active match
            existing = await service.list_memories(
                context.workspace.id, tier=payload.tier, include_superseded=False
            )
            if existing:
                mem = existing[0]
            else:
                mem = await service.create_memory(
                    context.workspace.id,
                    context.user.id,
                    payload.tier,
                    payload.content,
                    confidence=payload.confidence,
                    embedding=vector,
                )
    return MemoryResponse.model_validate(mem)


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: uuid.UUID,
    payload: MemoryUpdate,
    context: MemberContext,
    session: SessionDep,
) -> MemoryResponse:
    service = MemoryService(session)
    updated = await service.update_memory(
        context.workspace.id,
        memory_id,
        content=payload.content,
        status=payload.status,
        confidence=payload.confidence,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return MemoryResponse.model_validate(updated)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID,
    context: MemberContext,
    session: SessionDep,
) -> None:
    service = MemoryService(session)
    deleted = await service.delete_memory(context.workspace.id, memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
