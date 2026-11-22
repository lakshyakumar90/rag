"""Document upload, listing, retrieval and deletion endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from api.v1.dependencies import (
    MemberContext,
    UploaderContext,
    get_document_access_service,
    get_document_service,
    get_upload_rate_limiter,
)
from core.config import get_settings
from core.rate_limit import UserRateLimiter
from models import DocumentStatus
from schemas import (
    DocumentPage,
    DocumentResponse,
    DownloadUrlResponse,
    GrantResponse,
    GrantUpdate,
    SourceCreate,
)
from schemas.document import DocumentSnippetResponse
from services import DocumentAccessService, DocumentService, read_upload

router = APIRouter(prefix="/workspaces", tags=["documents"])


@router.post(
    "/{workspace_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document (PDF, DOCX, TXT, MD)",
)
async def upload_document(
    file: Annotated[UploadFile, File()],
    context: UploaderContext,
    service: Annotated[DocumentService, Depends(get_document_service)],
    limiter: Annotated[UserRateLimiter, Depends(get_upload_rate_limiter)],
) -> DocumentResponse:
    await limiter.check(context.user.id)
    data = await read_upload(file, get_settings().max_upload_size_bytes)
    return await service.upload(context, file.filename or "file", data)


@router.post(
    "/{workspace_id}/sources",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import a URL or GitHub repository through the ingestion pipeline",
)
async def create_source(
    payload: SourceCreate,
    context: UploaderContext,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentResponse:
    return await service.create_source(context, payload)


@router.get(
    "/{workspace_id}/documents",
    response_model=DocumentPage,
    summary="List workspace documents (paginated, filter by status)",
)
async def list_documents(
    context: MemberContext,
    service: Annotated[DocumentService, Depends(get_document_service)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
) -> DocumentPage:
    return await service.list_documents(context, skip, limit, status_filter)


@router.get(
    "/{workspace_id}/documents/{document_id}",
    response_model=DocumentResponse,
    summary="Get document metadata",
)
async def get_document(
    document_id: uuid.UUID,
    context: MemberContext,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentResponse:
    return await service.get(context, document_id)


@router.get(
    "/{workspace_id}/documents/{document_id}/chunks/{chunk_id}",
    response_model=DocumentSnippetResponse,
    summary="Read the exact text of a cited chunk",
)
async def get_document_snippet(
    document_id: uuid.UUID,
    chunk_id: uuid.UUID,
    context: MemberContext,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentSnippetResponse:
    return await service.snippet(context, document_id, chunk_id)


@router.get(
    "/{workspace_id}/documents/{document_id}/url",
    response_model=DownloadUrlResponse,
    summary="Get a presigned download URL",
)
async def document_download_url(
    document_id: uuid.UUID,
    context: MemberContext,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DownloadUrlResponse:
    return await service.download_url(context, document_id)


@router.get(
    "/{workspace_id}/documents/{document_id}/grants",
    response_model=GrantResponse,
    summary="List per-document grants (owner/admin only)",
)
async def list_grants(
    document_id: uuid.UUID,
    context: UploaderContext,
    service: Annotated[DocumentAccessService, Depends(get_document_access_service)],
    documents: Annotated[DocumentService, Depends(get_document_service)],
) -> GrantResponse:
    document = await documents.get(context, document_id)
    return GrantResponse(
        document_id=document_id,
        restricted=document.restricted,
        user_ids=await service.list_grants(context.workspace.id, document_id),
    )


@router.put(
    "/{workspace_id}/documents/{document_id}/grants",
    response_model=GrantResponse,
    summary="Replace per-document grants (owner/admin only)",
)
async def update_grants(
    document_id: uuid.UUID,
    payload: GrantUpdate,
    context: UploaderContext,
    service: Annotated[DocumentAccessService, Depends(get_document_access_service)],
) -> GrantResponse:
    users = await service.set_grants(
        context.workspace.id,
        document_id,
        context.user.id,
        payload.user_ids,
        payload.restricted,
    )
    return GrantResponse(
        document_id=document_id, restricted=payload.restricted, user_ids=users
    )


@router.post(
    "/{workspace_id}/documents/{document_id}/ocr-retry",
    response_model=DocumentResponse,
    summary="Re-run OCR/ingestion on an unreadable document without re-uploading",
)
async def retry_ocr(
    document_id: uuid.UUID,
    context: UploaderContext,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentResponse:
    return await service.reindex(context, document_id)


@router.post(
    "/{workspace_id}/documents/{document_id}/reindex",
    response_model=DocumentResponse,
    summary="Delete chunks and re-run ingestion (owner/admin only)",
)
async def reindex_document(
    document_id: uuid.UUID,
    context: UploaderContext,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentResponse:
    return await service.reindex(context, document_id)


@router.delete(
    "/{workspace_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and its stored file",
)
async def delete_document(
    document_id: uuid.UUID,
    context: UploaderContext,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> None:
    await service.delete(context, document_id)
