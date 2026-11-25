"""Tests for Contextual Retrieval and Small-to-Big parent-document chunking."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import get_settings
from core.prompting import build_context
from models import Document, DocumentChunk, DocumentStatus, User, Workspace
from workers.chunking import chunk_document, chunk_hierarchical
from workers.extraction import ExtractedPage, ExtractedSection, ExtractionResult
from workers.ingest import _process, generate_context_header


def test_hierarchical_chunking_links_children_to_parent_windows() -> None:
    paragraphs = [
        f"Paragraph {i}: Acme Corp expanded its Q2 enterprise cloud footprint "
        f"with automated failover and zero-downtime upgrades across region {i}."
        for i in range(40)
    ]
    section_text = "\n\n".join(paragraphs)
    extracted = ExtractionResult(
        pages=[ExtractedPage(1, section_text)],
        sections=[ExtractedSection(1, ("Acme Corp", "Q2 Expansion"), section_text)],
        page_count=1,
    )

    chunks = chunk_hierarchical(
        extracted,
        parent_target_tokens=300,
        parent_overlap_tokens=30,
        child_target_tokens=80,
        child_overlap_tokens=10,
    )
    assert len(chunks) > 4
    assert all(chunk.parent_text is not None for chunk in chunks)
    assert all(len(chunk.parent_text or "") >= len(chunk.text) for chunk in chunks)
    assert all(chunk.heading_path == ("Acme Corp", "Q2 Expansion") for chunk in chunks)
    # Multiple children share the same parent window
    unique_parents = {chunk.parent_text for chunk in chunks}
    assert len(unique_parents) < len(chunks)

    via_dispatch = chunk_document(
        extracted,
        strategy="hierarchical",
        overlap_tokens=10,
        parent_target_tokens=300,
        child_target_tokens=80,
    )
    assert len(via_dispatch) == len(chunks)


def test_prompting_packs_deduplicated_parent_content_with_child_citations() -> None:
    doc_id = uuid.uuid4()
    parent = (
        "Acme Corp Q2 Report: Revenue grew 42% YoY. "
        "The company launched AuroraDB in May and it reached 10,000 deployments."
    )
    child_1 = SimpleNamespace(
        chunk_id=uuid.uuid4(),
        document_id=doc_id,
        filename="q2-report.pdf",
        page_number=2,
        heading_path=["Financials", "Q2"],
        text="Revenue grew 42% YoY.",
        parent_content=parent,
    )
    child_2 = SimpleNamespace(
        chunk_id=uuid.uuid4(),
        document_id=doc_id,
        filename="q2-report.pdf",
        page_number=2,
        heading_path=["Financials", "Q2"],
        text="It reached 10,000 deployments.",
        parent_content=parent,
    )

    built = build_context([child_1, child_2], token_budget=2000)
    assert len(built.sources) == 2
    assert built.sources[0].chunk_id == child_1.chunk_id
    assert built.sources[1].chunk_id == child_2.chunk_id
    # Full parent text appears once; sibling chunk references source 1.
    assert built.text.count("AuroraDB in May") == 1
    assert "See parent section in source 1" in built.text


async def test_contextual_header_generation_with_llm_and_fallback() -> None:
    class FakeLLM:
        async def complete(self, req):
            return SimpleNamespace(
                text="From Acme Corp Q2 Financial Report, describing AuroraDB adoption."
            )

    header = await generate_context_header(
        "q2-report.pdf",
        ("Financials", "Q2"),
        "Acme Corp launched AuroraDB in Q2.",
        "It reached 10,000 deployments.",
        llm_provider=FakeLLM(),
    )
    assert "Acme Corp" in header
    assert "AuroraDB" in header

    fallback = await generate_context_header(
        "q2-report.pdf",
        ("Financials", "Q2"),
        "Acme Corp launched AuroraDB in Q2.",
        "It reached 10,000 deployments.",
        llm_provider=None,
    )
    assert "q2-report.pdf" in fallback
    assert "Financials > Q2" in fallback
    assert "Acme Corp" in fallback


async def test_ingest_contextual_hierarchical_stores_headers_and_parents(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "chunking_strategy", "hierarchical")
    monkeypatch.setattr(settings, "contextual_retrieval_enabled", True)
    monkeypatch.setattr(settings, "chunk_parent_tokens", 200)
    monkeypatch.setattr(settings, "chunk_child_tokens", 60)

    captured_embedded_texts: list[str] = []

    class RecordingEmbeddings:
        dimension = 4

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            captured_embedded_texts.extend(texts)
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    markdown_body = (
        b"# Acme Corp Q2 Report\n\n"
        b"Acme Corp released Project Nova in Q2 2026.\n\n"
        b"It achieved 99.99% uptime and the company doubled enterprise seats."
    )

    class FakeStorage:
        async def download(self, workspace_id: str, key: str) -> bytes:
            return markdown_body

    async with session_factory() as session:
        user = User(email="ctx@example.com", password_hash="hash")
        session.add(user)
        await session.flush()
        ws = Workspace(name="ctx-ws", slug="ctx-ws", created_by=user.id)
        session.add(ws)
        await session.flush()
        doc = Document(
            workspace_id=ws.id,
            uploaded_by=user.id,
            filename="acme-q2.md",
            mime_type="text/markdown",
            size=len(markdown_body),
            sha256="a" * 64,
            storage_key=f"{ws.id}/acme-q2.md",
            status=DocumentStatus.PENDING,
        )
        session.add(doc)
        await session.commit()
        doc_id = doc.id

    await _process(doc_id, session_factory, FakeStorage(), RecordingEmbeddings())  # type: ignore[arg-type]

    assert captured_embedded_texts
    # Context header containing document/section context was prepended before embedding
    assert any("acme-q2.md" in text for text in captured_embedded_texts)

    async with session_factory() as session:
        chunks = (
            await session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
            )
        ).scalars().all()
        assert len(chunks) >= 1
        assert all(chunk.parent_content is not None for chunk in chunks)
        assert all(chunk.context_header is not None for chunk in chunks)
        assert any("acme-q2.md" in (chunk.search_vector or "") for chunk in chunks)
