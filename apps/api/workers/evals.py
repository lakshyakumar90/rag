"""ARQ background task for running evaluation suites asynchronously."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models import EvalRun, Membership, MembershipRole, User, Workspace
from providers.embeddings import EmbeddingProvider
from providers.rerank import Reranker
from services.evals import EvalService
from services.qdrant_index import QdrantIndexService
from services.workspaces import WorkspaceContext


async def run_eval_suite(ctx: dict, run_id: str) -> None:
    """Execute a queued evaluation run against the workspace corpus."""
    factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    embeddings: EmbeddingProvider = ctx["embedding_provider"]
    indexer: QdrantIndexService | None = ctx.get("indexer")
    reranker = Reranker()
    try:
        async with factory() as session:
            run = await session.get(EvalRun, uuid.UUID(run_id))
            if run is None:
                return
            workspace = await session.get(Workspace, run.workspace_id)
            if workspace is None:
                return
            owner = (
                await session.execute(
                    select(User)
                    .join(Membership, Membership.user_id == User.id)
                    .where(Membership.workspace_id == workspace.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if owner is None:
                return
            context = WorkspaceContext(
                workspace=workspace,
                user=owner,
                role=MembershipRole.OWNER,
            )
            service = EvalService(session)
            await service.execute_run(
                run.id,
                context=context,
                embeddings=embeddings,
                reranker=reranker,
                indexer=indexer,
            )
    finally:
        await reranker.close()
