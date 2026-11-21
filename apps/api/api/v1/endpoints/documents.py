"""Document upload, listing, retrieval and deletion endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from api.v1.dependencies import (
    MemberContext,
    UploaderContext,
    get_document_service,
)
from core.config import get_settings
from models import DocumentStatus
from schemas import DocumentPage, DocumentResponse, DownloadUrlResponse
from services import DocumentService, read_upload

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
) -> DocumentResponse:
    data = await read_upload(file, get_settings().max_upload_size_bytes)
    return await service.upload(context, file.filename or "file", data)


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
