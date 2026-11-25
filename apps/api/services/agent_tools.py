"""Read-only agent tools with typed inputs/outputs and workspace checks."""

from __future__ import annotations

import html
import uuid
from html.parser import HTMLParser
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.calculator import CalculatorError, evaluate
from core.config import get_settings
from core.net import UnsafeBaseURLError, validate_base_url
from core.prompting import sanitize_context_text
from models import Document, DocumentChunk, DocumentStatus
from schemas import (
    CalculatorInput,
    CalculatorOutput,
    DocumentHit,
    DocumentSearchInput,
    DocumentSearchOutput,
    SummarizeInput,
    SummarizeOutput,
    WebHit,
    WebSearchInput,
    WebSearchOutput,
)
from services.document_access import DocumentAccessService
from services.exceptions import DocumentNotFoundError
from services.retrieval import RetrievalService
from services.workspaces import WorkspaceContext


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0
        self._title = False
        self.title = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        if tag == "title":
            self._title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._title = False

    def handle_data(self, data: str) -> None:
        if self._title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


class AgentTools:
    """All tools are read-only. Retrieved content is returned as untrusted data."""

    def __init__(
        self,
        session: AsyncSession,
        retrieval: RetrievalService,
        context: WorkspaceContext,
    ) -> None:
        self._session = session
        self._retrieval = retrieval
        self._context = context
        self._settings = get_settings()

    async def document_search(self, raw: dict) -> DocumentSearchOutput:
        args = DocumentSearchInput.model_validate(raw)
        response = await self._retrieval.search(
            self._context,
            args.query,
            top_k=args.top_k,
            document_ids=args.document_ids,
        )
        return DocumentSearchOutput(
            items=[
                DocumentHit(
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    filename=item.filename,
                    text=sanitize_context_text(item.text),
                    page_number=item.page_number,
                    heading_path=item.heading_path,
                )
                for item in response.items
            ]
        )

    async def web_search(self, raw: dict) -> WebSearchOutput:
        args = WebSearchInput.model_validate(raw)
        template = self._settings.agent_web_search_url
        if not template:
            return WebSearchOutput(
                items=[],
                unavailable_reason="Web search is not configured on this server.",
            )
        try:
            url = validate_base_url(template.replace("{query}", quote(args.query)))
        except UnsafeBaseURLError as exc:
            return WebSearchOutput(items=[], unavailable_reason=str(exc))
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.agent_web_search_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                body = response.text[: self._settings.agent_max_web_chars]
        except httpx.HTTPError as exc:
            return WebSearchOutput(
                items=[], unavailable_reason=f"Web search failed: {type(exc).__name__}"
            )
        parser = _TextExtractor()
        parser.feed(body)
        text = sanitize_context_text(" ".join(parser.parts))
        return WebSearchOutput(
            items=[
                WebHit(
                    title=html.unescape(parser.title.strip())[:200] or "Web result",
                    url=url,
                    snippet=text[:1500],
                )
            ][: args.max_results]
        )

    @staticmethod
    async def calculator(raw: dict) -> CalculatorOutput:
        args = CalculatorInput.model_validate(raw)
        try:
            value = evaluate(args.expression)
        except CalculatorError as exc:
            raise ValueError(str(exc)) from exc
        return CalculatorOutput(expression=args.expression, value=value)

    async def summarize_document(self, raw: dict) -> SummarizeOutput:
        args = SummarizeInput.model_validate(raw)
        workspace_id = self._context.workspace.id
        role = getattr(self._context.role, "value", self._context.role)
        if not await DocumentAccessService(self._session).can_access(
            workspace_id, self._context.user.id, str(role), args.document_id
        ):
            raise DocumentNotFoundError()
        document = (
            await self._session.execute(
                select(Document).where(
                    Document.id == args.document_id,
                    Document.workspace_id == workspace_id,
                    Document.status == DocumentStatus.READY,
                )
            )
        ).scalar_one_or_none()
        if document is None:
            raise DocumentNotFoundError()
        chunks = (
            (
                await self._session.execute(
                    select(DocumentChunk)
                    .where(
                        DocumentChunk.document_id == args.document_id,
                        DocumentChunk.workspace_id == workspace_id,
                    )
                    .order_by(DocumentChunk.page_number, DocumentChunk.chunk_index)
                )
            )
            .scalars()
            .all()
        )
        pages = sorted({chunk.page_number for chunk in chunks if chunk.page_number})
        summary = " ".join(
            sanitize_context_text(chunk.content) for chunk in chunks[:20]
        )[:2000]
        return SummarizeOutput(
            document_id=document.id,
            filename=document.filename,
            summary=summary or "No text available to summarize.",
            pages=pages,
        )

    async def run(self, name: str, arguments: dict):
        if name == "document_search":
            return await self.document_search(arguments)
        if name == "web_search":
            return await self.web_search(arguments)
        if name == "calculator":
            return await self.calculator(arguments)
        if name == "summarize_document":
            return await self.summarize_document(arguments)
        raise ValueError(f"unknown tool: {name}")

    async def compare_documents(
        self,
        document_ids: list[uuid.UUID],
        criteria: list[str],
    ) -> dict:
        """Compare multiple documents across criteria into a cited Markdown table."""
        from sqlalchemy import select

        from models import Document

        if not document_ids or not criteria:
            return {"markdown_table": "", "citations": []}

        docs = (
            (
                await self._session.execute(
                    select(Document).where(
                        Document.workspace_id == self._context.workspace.id,
                        Document.id.in_(document_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        doc_by_id = {d.id: d for d in docs}
        ordered_ids = [did for did in document_ids if did in doc_by_id]
        if not ordered_ids:
            return {"markdown_table": "", "citations": []}

        citations: list[dict] = []
        cite_index: dict[uuid.UUID, int] = {}

        def _register_citation(item) -> int:
            if item.chunk_id not in cite_index:
                num = len(citations) + 1
                cite_index[item.chunk_id] = num
                citations.append(
                    {
                        "number": num,
                        "chunk_id": str(item.chunk_id),
                        "document_id": str(item.document_id),
                        "filename": item.filename,
                        "page_number": item.page_number,
                        "heading_path": item.heading_path,
                    }
                )
            return cite_index[item.chunk_id]

        headers = ["Criterion"] + [doc_by_id[did].filename for did in ordered_ids]
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]

        for criterion in criteria:
            # Shared AsyncSession is not concurrency-safe for parallel commits.
            results = [
                await self._retrieval.search(
                    self._context,
                    criterion,
                    top_k=1,
                    document_ids=[did],
                )
                for did in ordered_ids
            ]
            cells = [criterion]
            for res in results:
                if res.items:
                    top = res.items[0]
                    num = _register_citation(top)
                    snippet = " ".join(top.text.split())[:140].replace("|", "/")
                    cells.append(f"{snippet} [{num}]")
                else:
                    cells.append("Not mentioned")
            lines.append("| " + " | ".join(cells) + " |")

        return {"markdown_table": "\n".join(lines), "citations": citations}
