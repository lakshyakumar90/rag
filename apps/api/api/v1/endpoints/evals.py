"""REST endpoints for evaluation datasets, cases, and runs."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.dependencies import (
    MemberContext,
    get_embedding_provider,
    get_job_queue,
    get_qdrant_indexer,
    get_reranker,
)
from core.database import get_session
from providers.embeddings import EmbeddingProvider
from providers.queue import JobQueue
from providers.rerank import Reranker
from schemas.evals import (
    EvalCaseCreate,
    EvalCaseResponse,
    EvalDatasetCreate,
    EvalDatasetResponse,
    EvalResultResponse,
    EvalRunCreate,
    EvalRunDetailResponse,
    EvalRunResponse,
)
from services.evals import EvalService
from services.qdrant_index import QdrantIndexService

router = APIRouter(prefix="/workspaces/{workspace_id}/evals", tags=["evals"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
EmbeddingsDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
RerankerDep = Annotated[Reranker, Depends(get_reranker)]
IndexerDep = Annotated[QdrantIndexService | None, Depends(get_qdrant_indexer)]
QueueDep = Annotated[JobQueue, Depends(get_job_queue)]


def _to_run_response(run) -> EvalRunResponse:
    return EvalRunResponse(
        id=run.id,
        dataset_id=run.dataset_id,
        workspace_id=run.workspace_id,
        status=run.status,
        top_k=run.top_k,
        total_cases=run.total_cases,
        completed_cases=run.completed_cases,
        recall_at_k=run.recall_at_k,
        mrr=run.mrr,
        ndcg_at_k=run.ndcg_at_k,
        faithfulness=run.faithfulness,
        answer_relevancy=run.answer_relevancy,
        citation_accuracy=run.citation_accuracy,
        error=run.error,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


def _to_result_response(row) -> EvalResultResponse:
    return EvalResultResponse(
        id=row.id,
        run_id=row.run_id,
        case_id=row.case_id,
        question=row.question,
        generated_answer=row.generated_answer,
        retrieved_document_ids=row.retrieved_document_ids,
        retrieved_chunk_ids=row.retrieved_chunk_ids,
        recall_at_k=row.recall_at_k,
        mrr=row.mrr,
        ndcg_at_k=row.ndcg_at_k,
        faithfulness=row.faithfulness,
        answer_relevancy=row.answer_relevancy,
        citation_accuracy=row.citation_accuracy,
        judge_reasoning=row.judge_reasoning,
        passed=row.passed,
        latency_ms=row.latency_ms,
    )


@router.post(
    "/datasets",
    response_model=EvalDatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dataset(
    payload: EvalDatasetCreate,
    context: MemberContext,
    session: SessionDep,
) -> EvalDatasetResponse:
    service = EvalService(session)
    ds = await service.create_dataset(
        context.workspace.id, context.user.id, payload.name, payload.description
    )
    return EvalDatasetResponse(
        id=ds.id,
        workspace_id=ds.workspace_id,
        name=ds.name,
        description=ds.description,
        case_count=0,
        created_at=ds.created_at,
    )


@router.get("/datasets", response_model=list[EvalDatasetResponse])
async def list_datasets(
    context: MemberContext,
    session: SessionDep,
) -> list[EvalDatasetResponse]:
    service = EvalService(session)
    items = await service.list_datasets(context.workspace.id)
    return [
        EvalDatasetResponse(
            id=ds.id,
            workspace_id=ds.workspace_id,
            name=ds.name,
            description=ds.description,
            case_count=count,
            created_at=ds.created_at,
        )
        for ds, count in items
    ]


@router.post(
    "/datasets/{dataset_id}/cases",
    response_model=EvalCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_case(
    dataset_id: uuid.UUID,
    payload: EvalCaseCreate,
    context: MemberContext,
    session: SessionDep,
) -> EvalCaseResponse:
    service = EvalService(session)
    case = await service.add_case(
        context.workspace.id,
        dataset_id,
        question=payload.question,
        expected_answer=payload.expected_answer,
        expected_document_ids=payload.expected_document_ids,
        expected_chunk_ids=payload.expected_chunk_ids,
        expected_keywords=payload.expected_keywords,
        source_message_id=payload.source_message_id,
    )
    return EvalCaseResponse(
        id=case.id,
        dataset_id=case.dataset_id,
        workspace_id=case.workspace_id,
        question=case.question,
        expected_answer=case.expected_answer,
        expected_document_ids=case.expected_document_ids,
        expected_chunk_ids=case.expected_chunk_ids,
        expected_keywords=case.expected_keywords,
        source_message_id=case.source_message_id,
        created_at=case.created_at,
    )


@router.get("/datasets/{dataset_id}/cases", response_model=list[EvalCaseResponse])
async def list_cases(
    dataset_id: uuid.UUID,
    context: MemberContext,
    session: SessionDep,
) -> list[EvalCaseResponse]:
    service = EvalService(session)
    cases = await service.list_cases(context.workspace.id, dataset_id)
    return [
        EvalCaseResponse(
            id=case.id,
            dataset_id=case.dataset_id,
            workspace_id=case.workspace_id,
            question=case.question,
            expected_answer=case.expected_answer,
            expected_document_ids=case.expected_document_ids,
            expected_chunk_ids=case.expected_chunk_ids,
            expected_keywords=case.expected_keywords,
            source_message_id=case.source_message_id,
            created_at=case.created_at,
        )
        for case in cases
    ]


@router.post(
    "/datasets/{dataset_id}/runs",
    response_model=EvalRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def trigger_run(
    dataset_id: uuid.UUID,
    payload: EvalRunCreate,
    context: MemberContext,
    session: SessionDep,
    embeddings: EmbeddingsDep,
    reranker: RerankerDep,
    indexer: IndexerDep,
    queue: QueueDep,
) -> EvalRunResponse:
    service = EvalService(session)
    run = await service.create_run(
        context.workspace.id, dataset_id, top_k=payload.top_k
    )
    if payload.run_async and hasattr(queue, "enqueue_eval_suite"):
        await queue.enqueue_eval_suite(run.id)
        return _to_run_response(run)
    completed = await service.execute_run(
        run.id,
        context=context,
        embeddings=embeddings,
        reranker=reranker,
        indexer=indexer,
    )
    return _to_run_response(completed)


@router.get("/runs", response_model=list[EvalRunResponse])
async def list_runs(
    context: MemberContext,
    session: SessionDep,
) -> list[EvalRunResponse]:
    service = EvalService(session)
    runs = await service.list_runs(context.workspace.id)
    return [_to_run_response(run) for run in runs]


@router.get("/runs/{run_id}", response_model=EvalRunDetailResponse)
async def get_run_detail(
    run_id: uuid.UUID,
    context: MemberContext,
    session: SessionDep,
) -> EvalRunDetailResponse:
    service = EvalService(session)
    run, results = await service.get_run_with_results(context.workspace.id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    mapped = [_to_result_response(row) for row in results]
    return EvalRunDetailResponse(
        **_to_run_response(run).model_dump(),
        results=mapped,
        failures=[row for row in mapped if not row.passed],
    )
