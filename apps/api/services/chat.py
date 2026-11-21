"""Grounded RAG answering: retrieve, build context, prompt, map citations."""

import uuid

from core.config import get_settings
from core.prompting import SYSTEM_PROMPT, build_context, parse_citations
from providers.llm.registry import create_llm_provider
from providers.llm.types import ChatMessage
from schemas import ChatResponse, Citation, SourceRef
from services.retrieval import RetrievalService
from services.workspaces import WorkspaceContext


class ChatService:
    def __init__(self, retrieval: RetrievalService) -> None:
        self._retrieval = retrieval

    async def answer(
        self,
        context: WorkspaceContext,
        query: str,
        top_k: int | None = None,
        document_ids: list[uuid.UUID] | None = None,
        provider_name: str | None = None,
    ) -> ChatResponse:
        settings = get_settings()
        provider_name = (
            provider_name or settings.chat_default_provider or settings.llm_provider
        )

        search = await self._retrieval.search(
            context, query, top_k=top_k, document_ids=document_ids
        )
        sources_refs = [
            self._source_ref(item, number)
            for number, item in enumerate(search.items, start=1)
        ]
        if not search.answerable or not search.items:
            # No evidence: do not call the model, and never invent an answer.
            return ChatResponse(
                answer="I don't know",
                answerable=False,
                provider=provider_name,
                citations=[],
                sources=sources_refs,
            )

        built = build_context(search.items, settings.prompt_context_token_budget)
        if not built.sources:
            return ChatResponse(
                answer="I don't know",
                answerable=False,
                provider=provider_name,
                citations=[],
                sources=sources_refs,
            )

        provider = create_llm_provider(provider_name)
        try:
            completion = await provider.complete(
                [
                    ChatMessage(role="system", content=SYSTEM_PROMPT),
                    ChatMessage(
                        role="user", content=f"Question: {query}\n\n{built.text}"
                    ),
                ],
                max_tokens=settings.chat_max_tokens,
            )
        finally:
            close = getattr(provider, "close", None)
            if close:
                await close()

        citations = parse_citations(completion.text, built.sources)
        return ChatResponse(
            answer=completion.text,
            answerable=True,
            provider=provider_name,
            citations=[
                Citation(
                    number=citation.number,
                    chunk_id=citation.chunk_id,
                    document_id=citation.document_id,
                    filename=citation.filename,
                    page_number=citation.page_number,
                    heading_path=citation.heading_path,
                )
                for citation in citations
            ],
            sources=[
                SourceRef(
                    number=source.number,
                    chunk_id=source.chunk_id,
                    document_id=source.document_id,
                    filename=source.filename,
                    page_number=source.page_number,
                    heading_path=source.heading_path,
                )
                for source in built.sources
            ],
        )

    @staticmethod
    def _source_ref(item, number: int) -> SourceRef:
        return SourceRef(
            number=number,
            chunk_id=item.chunk_id,
            document_id=item.document_id,
            filename=item.filename,
            page_number=item.page_number,
            heading_path=item.heading_path,
        )
