"""Hybrid search endpoint for workspace documents."""

from typing import Annotated

from fastapi import APIRouter, Depends

from api.v1.dependencies import MemberContext, get_retrieval_service
from schemas import SearchRequest, SearchResponse
from services import RetrievalService

router = APIRouter(prefix="/workspaces", tags=["retrieval"])


@router.post(
    "/{workspace_id}/search",
    response_model=SearchResponse,
    summary="Search workspace documents (vector + keyword, fused with RRF)",
)
async def search(
    payload: SearchRequest,
    context: MemberContext,
    service: Annotated[RetrievalService, Depends(get_retrieval_service)],
) -> SearchResponse:
    return await service.search(
        context, payload.query, payload.top_k, payload.document_ids
    )
