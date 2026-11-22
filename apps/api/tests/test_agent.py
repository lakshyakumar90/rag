"""Bounded agent loop: typed tools, permissions and step limits."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.calculator import CalculatorError, evaluate
from models import Document, DocumentStatus, User, Workspace
from schemas import AgentRequest, SearchResponse, SearchResult
from services.agent import AgentService
from services.workspaces import WorkspaceContext

PROFILE = "ollama-embeddinggemma-768-v1"


def test_calculator_is_constrained() -> None:
    assert evaluate("2*(3+4)") == 14.0
    assert evaluate("-3 ** 2 + 1") == -8.0
    with pytest.raises(CalculatorError):
        evaluate("__import__('os').system('echo hi')")
    with pytest.raises(CalculatorError):
        evaluate("().__class__")
    with pytest.raises(CalculatorError):
        evaluate("1/0")


class FakeProvider:
    def __init__(self, plans: list[dict]) -> None:
        self.plans = list(plans)
        self.calls = 0

    async def complete(self, messages, **opts):
        import json

        from providers.llm.types import Completion

        plan = self.plans[min(self.calls, len(self.plans) - 1)]
        self.calls += 1
        return Completion(text=json.dumps(plan), finish_reason="stop")

    async def close(self) -> None:
        return None


class FakeRetrieval:
    async def search(self, context, query, **kwargs) -> SearchResponse:
        return SearchResponse(
            answer=None,
            answerable=True,
            threshold=0.15,
            items=[
                SearchResult(
                    chunk_id=uuid.uuid4(),
                    document_id=uuid.uuid4(),
                    filename="evidence.txt",
                    text="The gateway is Frankfurt.",
                    score=1.0,
                    page_number=2,
                    heading_path=None,
                )
            ],
        )


async def _context(factory: async_sessionmaker[AsyncSession], role: str = "owner"):
    async with factory() as session:
        user = User(
            email=f"agent-{uuid.uuid4()}@example.com",
            password_hash="not-used",
        )
        session.add(user)
        await session.flush()
        workspace = Workspace(
            name="Agent", slug=f"agent-{uuid.uuid4().hex[:8]}", created_by=user.id
        )
        session.add(workspace)
        await session.flush()
        document = Document(
            workspace_id=workspace.id,
            uploaded_by=user.id,
            filename="private.txt",
            mime_type="text/plain",
            size=50,
            sha256=uuid.uuid4().hex,
            storage_key=f"{workspace.id}/private",
            status=DocumentStatus.READY,
            restricted=True,
        )
        session.add(document)
        await session.commit()
        return WorkspaceContext(user=user, workspace=workspace, role=role), document.id


async def test_agent_runs_tool_and_emits_events(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    context, _ = await _context(session_factory)
    provider = FakeProvider(
        [
            {"tool": "calculator", "arguments": {"expression": "6*7"}},
            {"answer": "The answer is 42 [1]."},
        ]
    )
    import services.agent as module

    monkeypatch.setattr(module, "create_llm_provider", lambda name: provider)
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    async with session_factory() as session:
        service = AgentService(session, FakeRetrieval(), None)
        result = await service.run(
            context, AgentRequest(query="What is 6 times 7?"), on_event
        )

    assert result["answer"] == "The answer is 42 [1]."
    assert result["steps"] == 1
    assert [event["type"] for event in events] == [
        "tool_start",
        "tool_result",
        "done",
    ]
    assert "42.0" in events[1]["detail"]


async def test_agent_stops_at_step_limit(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    context, _ = await _context(session_factory)
    provider = FakeProvider(
        [{"tool": "calculator", "arguments": {"expression": "1+1"}}]
    )
    import services.agent as module

    monkeypatch.setattr(module, "create_llm_provider", lambda name: provider)
    async with session_factory() as session:
        service = AgentService(session, FakeRetrieval(), None)
        result = await service.run(context, AgentRequest(query="loop", max_steps=2))
    assert result["steps"] == 2
    assert "step limit" in result["answer"]


async def test_summarize_respects_document_grants(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context, document_id = await _context(session_factory, role="member")
    from services.agent_tools import AgentTools

    async with session_factory() as session:
        tools = AgentTools(session, FakeRetrieval(), context)
        from services.exceptions import DocumentNotFoundError

        with pytest.raises(DocumentNotFoundError):
            await tools.summarize_document({"document_id": str(document_id)})
