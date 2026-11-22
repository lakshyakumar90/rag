"""Bring-your-own embedding profiles: validation and build-before-switch."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.crypto import decrypt_secret, encrypt_secret
from core.net import UnsafeBaseURLError, validate_base_url
from models import Document, DocumentChunk, DocumentStatus, EmbeddingProfile, Workspace
from providers.embeddings import get_profile_embedding_provider
from providers.qdrant import collection_name
from providers.queue import JobQueue
from schemas import (
    EmbeddingProfileCreate,
    EmbeddingProfileResponse,
    EmbeddingProfileValidation,
)
from services.exceptions import DomainError
from services.qdrant_index import QdrantIndexService


class ProfileNotFoundError(DomainError):
    status_code = 404
    code = "EMBEDDING_PROFILE_NOT_FOUND"
    message = "Embedding profile not found"


class ProfileNotValidatedError(DomainError):
    status_code = 400
    code = "EMBEDDING_PROFILE_NOT_VALIDATED"
    message = "Validate the embedding profile before using it"


class ProfileInUseError(DomainError):
    status_code = 409
    code = "EMBEDDING_PROFILE_IN_USE"
    message = "An active workspace profile cannot be disabled"


SUPPORTED = {"ollama", "openai", "openai-compatible"}


def _response(profile: EmbeddingProfile) -> EmbeddingProfileResponse:
    config = profile.config_json or {}
    return EmbeddingProfileResponse(
        id=profile.id,
        name=profile.name,
        provider=profile.provider,
        model=profile.model,
        dimension=profile.dimension,
        distance=profile.distance,
        version=profile.version,
        enabled=profile.enabled,
        validated_at=profile.validated_at,
        has_api_key=bool(config.get("encrypted_api_key")),
    )


class EmbeddingProfileService:
    def __init__(
        self,
        session: AsyncSession,
        queue: JobQueue | None = None,
        indexer: QdrantIndexService | None = None,
    ) -> None:
        self._session = session
        self._queue = queue
        self._indexer = indexer

    async def list(self) -> list[EmbeddingProfileResponse]:
        profiles = (
            (
                await self._session.execute(
                    select(EmbeddingProfile).order_by(EmbeddingProfile.name)
                )
            )
            .scalars()
            .all()
        )
        return [_response(profile) for profile in profiles]

    async def create(self, payload: EmbeddingProfileCreate) -> EmbeddingProfileResponse:
        if payload.provider not in SUPPORTED:
            raise DomainError(
                message=f"Unsupported embedding provider: {payload.provider}"
            )
        config: dict = {}
        if payload.base_url:
            try:
                config["base_url"] = validate_base_url(payload.base_url)
            except UnsafeBaseURLError as exc:
                raise DomainError(message=str(exc)) from exc
        if payload.api_key:
            config["encrypted_api_key"] = encrypt_secret(payload.api_key)
        profile = EmbeddingProfile(
            name=payload.name,
            provider=payload.provider,
            model=payload.model,
            dimension=payload.dimension,
            distance=payload.distance,
            version=payload.version,
            enabled=False,
            config_json=config or None,
        )
        self._session.add(profile)
        await self._session.commit()
        return _response(profile)

    async def get(self, name: str) -> EmbeddingProfile:
        profile = (
            await self._session.execute(
                select(EmbeddingProfile).where(EmbeddingProfile.name == name)
            )
        ).scalar_one_or_none()
        if profile is None:
            raise ProfileNotFoundError()
        return profile

    async def validate(self, name: str) -> EmbeddingProfileValidation:
        """Enable a profile only after a real sample embedding matches its shape."""
        profile = await self.get(name)
        provider = None
        try:
            config = profile.config_json or {}
            if config.get("encrypted_api_key"):
                config = {
                    **config,
                    "api_key": decrypt_secret(config["encrypted_api_key"]),
                }
            provider = get_profile_embedding_provider(
                SimpleNamespace(
                    provider=profile.provider,
                    model=profile.model,
                    dimension=profile.dimension,
                    config_json=config,
                )
            )
            vector = await provider.embed_query("embedding profile validation sample")
        except Exception as exc:  # noqa: BLE001 - report detail to the caller
            return EmbeddingProfileValidation(
                ok=False, detail=f"Validation failed: {type(exc).__name__}: {exc}"[:300]
            )
        finally:
            if provider is not None:
                await provider.close()
        if len(vector) != profile.dimension:
            return EmbeddingProfileValidation(
                ok=False,
                detail=f"Expected {profile.dimension} dimensions, got {len(vector)}",
                dimension=len(vector),
            )
        profile.validated_at = datetime.now(UTC)
        profile.enabled = True
        await self._session.commit()
        return EmbeddingProfileValidation(
            ok=True, detail="Profile validated.", dimension=len(vector)
        )

    async def disable(self, name: str) -> None:
        profile = await self.get(name)
        in_use = (
            await self._session.execute(
                select(Workspace.id).where(Workspace.active_embedding_profile == name)
            )
        ).first()
        if in_use is not None:
            raise ProfileInUseError()
        profile.enabled = False
        await self._session.commit()

    async def request_switch(self, workspace_id: uuid.UUID, name: str) -> dict:
        profile = await self.get(name)
        if not profile.enabled:
            raise ProfileNotValidatedError()
        if self._queue is None:
            raise DomainError(message="Background queue is unavailable")
        job_id = await self._queue.enqueue_profile_switch(workspace_id, name)
        return {"workspace_id": str(workspace_id), "profile": name, "job_id": job_id}

    async def build_switch(self, workspace_id: uuid.UUID, name: str) -> None:
        """Build the replacement collection, then flip the workspace in one go."""
        profile = await self.get(name)
        provider = None
        try:
            config = profile.config_json or {}
            if config.get("encrypted_api_key"):
                config = {
                    **config,
                    "api_key": decrypt_secret(config["encrypted_api_key"]),
                }
            provider = get_profile_embedding_provider(
                SimpleNamespace(
                    provider=profile.provider,
                    model=profile.model,
                    dimension=profile.dimension,
                    config_json=config,
                )
            )
            documents = (
                (
                    await self._session.execute(
                        select(Document).where(
                            Document.workspace_id == workspace_id,
                            Document.status == DocumentStatus.READY,
                        )
                    )
                )
                .scalars()
                .all()
            )
            name_collection = collection_name(profile.name)
            if self._indexer is not None:
                await self._indexer.prepare(profile.name, profile.dimension)
            client = self._indexer.client if self._indexer else None
            if client is None:
                raise DomainError(message="Qdrant is not configured")
            for document in documents:
                chunks = (
                    (
                        await self._session.execute(
                            select(DocumentChunk).where(
                                DocumentChunk.document_id == document.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                texts = [chunk.content for chunk in chunks]
                vectors = await provider.embed_documents(texts) if texts else []
                points = [
                    {
                        "id": str(chunk.id),
                        "vector": vector,
                        "payload": {
                            "workspace_id": str(workspace_id),
                            "document_id": str(document.id),
                            "embedding_profile": profile.name,
                            "index_version": document.index_version + 1,
                            "chunk_index": chunk.chunk_index,
                            "page_number": chunk.page_number,
                        },
                    }
                    for chunk, vector in zip(chunks, vectors, strict=True)
                ]
                if points:
                    await client.upsert(name_collection, points, wait=True)
                await self._session.execute(
                    update(Document)
                    .where(Document.id == document.id)
                    .values(
                        embedding_profile=profile.name,
                        embedding_model=profile.model,
                        embedding_dim=profile.dimension,
                        index_version=document.index_version + 1,
                        chunks_indexed=len(points),
                    )
                )
                await self._session.commit()
            # The flip happens only after every document has a replacement index.
            await self._session.execute(
                update(Workspace)
                .where(Workspace.id == workspace_id)
                .values(active_embedding_profile=profile.name)
            )
            await self._session.commit()
        finally:
            if provider is not None:
                await provider.close()
