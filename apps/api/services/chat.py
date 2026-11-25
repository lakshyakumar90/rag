"""Grounded RAG answering with optional conversation history."""

import asyncio
import inspect
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from core.config import get_settings
from core.prompting import SYSTEM_PROMPT, build_context, parse_citations
from providers.llm.base import LLMProvider
from providers.llm.registry import create_llm_provider
from providers.llm.types import ChatMessage, Error, TextDelta, Usage
from schemas import ChatResponse, Citation, SourceRef
from services.ai_settings import AISettingsService
from services.confidence import compute_answer_confidence
from services.conversations import ConversationService
from services.retrieval import RetrievalService
from services.workspaces import WorkspaceContext
from workers.tokenization import count_tokens

# Active SSE streams by conversation, so a stop request can cancel generation.
active_streams: dict[uuid.UUID, asyncio.Task] = {}


def cancel_stream(conversation_id: uuid.UUID) -> bool:
    """Cancel an in-flight stream in this process; False if none is active."""
    task = active_streams.get(conversation_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def _model_options(provider: object, method: str, model: str | None) -> dict[str, str]:
    """Pass ``model`` only to adapters that accept it (test doubles often don't)."""
    if not model:
        return {}
    function = getattr(provider, method, None)
    if function is None:
        return {}
    parameters = inspect.signature(function).parameters.values()
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD or parameter.name == "model"
        for parameter in parameters
    ):
        return {"model": model}
    return {}


def _model_name(provider_name: str) -> str | None:
    settings = get_settings()
    if provider_name in ("openai", "openai-compatible"):
        return settings.openai_model
    if provider_name == "anthropic":
        return settings.anthropic_model
    if provider_name == "ollama":
        return settings.ollama_llm_model
    if provider_name == "cli-codex":
        return settings.cli_codex_model
    if provider_name == "cli-opencode":
        return settings.cli_opencode_model or provider_name
    if provider_name.startswith("cli-"):
        return provider_name
    return None


class ChatService:
    def __init__(
        self,
        retrieval: RetrievalService,
        conversations: ConversationService | None = None,
        defaults: AISettingsService | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._conversations = conversations
        self._defaults = defaults

    async def _create_provider(self, context: WorkspaceContext, name: str):
        if name.startswith("config:") and self._defaults is not None:
            return await self._defaults.provider_for(context.user.id, name)
        return create_llm_provider(name)

    async def _selection(
        self,
        context: WorkspaceContext,
        provider_name: str | None,
        model: str | None,
        conversation,
    ) -> tuple[str, str | None]:
        """Resolve provider/model: explicit > conversation > Settings > server."""
        settings = get_settings()
        if not provider_name and conversation is not None:
            provider_name = getattr(conversation, "provider", None)
            model = model or getattr(conversation, "model", None)
        if not provider_name and self._defaults is not None:
            defaults = await self._defaults.get_defaults(context.user.id)
            provider_name = defaults.provider
            model = model or defaults.model
        provider_name = (
            provider_name or settings.chat_default_provider or settings.llm_provider
        )
        return provider_name, model or _model_name(provider_name)

    async def answer(
        self,
        context: WorkspaceContext,
        query: str,
        top_k: int | None = None,
        document_ids: list[uuid.UUID] | None = None,
        provider_name: str | None = None,
        conversation_id: uuid.UUID | None = None,
        model: str | None = None,
    ) -> ChatResponse:
        settings = get_settings()

        conversation = None
        history = []
        conversations = self._conversations
        if conversation_id is not None:
            if conversations is None:
                raise RuntimeError("conversation support is not configured")
            conversation = await conversations.get(context, conversation_id)
            history = await conversations.messages(context, conversation_id)

        provider_name, model = await self._selection(
            context, provider_name, model, conversation
        )

        provider: LLMProvider | None = None
        if conversation is not None:
            assert conversations is not None
            provider = await self._create_provider(context, provider_name)
            # Follow-ups ("what about the second one?") need a standalone query.
            effective_query = await conversations.rewrite_query(
                history, query, provider
            )
        else:
            effective_query = query

        search = await self._retrieval.search(
            context, effective_query, top_k=top_k, document_ids=document_ids
        )
        sources_refs = [
            self._source_ref(item, number)
            for number, item in enumerate(search.items, start=1)
        ]
        if not search.answerable or not search.items:
            answer_text = "I don't know"
            citations: list = []
            sources = sources_refs
            usage = None
            latency = 0
        else:
            built = build_context(search.items, settings.prompt_context_token_budget)
            if not built.sources:
                answer_text = "I don't know"
                citations, sources, usage, latency = [], sources_refs, None, 0
            else:
                messages = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
                if conversation is not None:
                    assert conversations is not None
                    for item in conversations.truncate_history(history):
                        if item.role in ("user", "assistant"):
                            messages.append(
                                ChatMessage(role=item.role, content=item.content)
                            )
                messages.append(
                    ChatMessage(
                        role="user",
                        content=f"Question: {effective_query}\n\n{built.text}",
                    )
                )
                if provider is None:
                    provider = await self._create_provider(context, provider_name)
                started = time.monotonic()
                try:
                    completion = await provider.complete(
                        messages,
                        max_tokens=settings.chat_max_tokens,
                        **_model_options(provider, "complete", model),
                    )
                finally:
                    latency = int((time.monotonic() - started) * 1000)
                answer_text = completion.text
                usage = completion.usage
                sources = [
                    SourceRef(
                        number=source.number,
                        chunk_id=source.chunk_id,
                        document_id=source.document_id,
                        filename=source.filename,
                        page_number=source.page_number,
                        heading_path=source.heading_path,
                    )
                    for source in built.sources
                ]
                citations = [
                    Citation(
                        number=citation.number,
                        chunk_id=citation.chunk_id,
                        document_id=citation.document_id,
                        filename=citation.filename,
                        page_number=citation.page_number,
                        heading_path=citation.heading_path,
                    )
                    for citation in parse_citations(answer_text, built.sources)
                ]

        new_title: str | None = None
        if (
            conversation is not None
            and conversations is not None
            and provider is not None
            and not history
            and conversation.title == "New conversation"
        ):
            new_title = await conversations.generate_title(query, provider)

        if provider is not None:
            close = getattr(provider, "close", None)
            if close:
                await close()

        is_answerable = answer_text != "I don't know"
        confidence = await compute_answer_confidence(
            answer=answer_text,
            answerable=is_answerable,
            search_items=search.items,
            valid_source_numbers={s.number for s in sources},
        )
        diagnostics = {
            "rewritten_query": effective_query,
            "retrieval_ms": search.retrieval_ms,
            "reranked": search.reranked,
            "cache_hit": search.cache_hit,
            "chunks": [
                {
                    "chunk_id": str(item.chunk_id),
                    "filename": item.filename,
                    "page_number": item.page_number,
                    "dense_rank": item.dense_rank,
                    "lexical_rank": item.lexical_rank,
                    "rrf_score": item.rrf_score,
                    "rerank_score": item.rerank_score,
                    "score": item.score,
                }
                for item in search.items
            ],
        }
        if conversation is not None and conversations is not None:
            await self._persist(
                conversations,
                conversation,
                query,
                answer_text,
                provider_name,
                citations,
                usage,
                latency,
                new_title,
                answerable=is_answerable,
                model=model,
                confidence_score=confidence.score,
                confidence_level=confidence.level,
                confidence_breakdown=confidence.breakdown,
                retrieval_diagnostics=diagnostics,
            )

        return ChatResponse(
            answer=answer_text,
            answerable=is_answerable,
            provider=provider_name,
            model=model,
            citations=citations,
            sources=sources,
            conversation_id=conversation_id,
            confidence_score=confidence.score,
            confidence_level=confidence.level,
            confidence_breakdown=confidence.breakdown,
            retrieval_diagnostics=diagnostics,
        )

    async def _persist(
        self,
        conversations: ConversationService,
        conversation,
        query: str,
        answer: str,
        provider_name: str,
        citations: list,
        usage,
        latency: int,
        new_title: str | None,
        prompt_text: str = "",
        answerable: bool | None = None,
        model: str | None = None,
        confidence_score: float | None = None,
        confidence_level: str | None = None,
        confidence_breakdown: dict | None = None,
        retrieval_diagnostics: dict | None = None,
    ) -> None:
        model = model or _model_name(provider_name)
        tokens_estimated = usage is None
        input_tokens = usage.input_tokens if usage else count_tokens(prompt_text)
        output_tokens = usage.output_tokens if usage else count_tokens(answer)
        await conversations.add_message(
            conversation.id, role="user", content=query, commit=False
        )
        await conversations.add_message(
            conversation.id,
            role="assistant",
            content=answer,
            citations=[
                {
                    **item.model_dump(),
                    "chunk_id": str(item.chunk_id),
                    "document_id": str(item.document_id),
                }
                for item in citations
            ],
            provider=provider_name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency,
            tokens_estimated=tokens_estimated,
            answerable=answerable,
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            confidence_breakdown=confidence_breakdown,
            retrieval_diagnostics=retrieval_diagnostics,
        )
        if new_title:
            conversation.title = new_title
        await conversations.commit()

    async def stream_answer(
        self,
        context: WorkspaceContext,
        query: str,
        top_k: int | None = None,
        document_ids: list[uuid.UUID] | None = None,
        provider_name: str | None = None,
        conversation_id: uuid.UUID | None = None,
        is_disconnected: Callable[[], Awaitable[bool]] | None = None,
        model: str | None = None,
    ) -> AsyncIterator[dict]:
        """Yield normalized SSE events, persisting the answer even on disconnect."""
        settings = get_settings()
        conversations = self._conversations
        conversation = None
        history: list = []
        provider: LLMProvider | None = None
        collected: list[str] = []
        citations: list[Citation] = []
        sources: list[SourceRef] = []
        usage: Usage | None = None
        latency = 0
        final_text = ""
        prompt_text = ""
        new_title: str | None = None
        answerable = False
        confidence_result = None
        diagnostics: dict | None = None

        if conversation_id is not None:
            if conversations is None:
                raise RuntimeError("conversation support is not configured")
            conversation = await conversations.get(context, conversation_id)
            history = await conversations.messages(context, conversation_id)
            task = asyncio.current_task()
            if task is not None:
                active_streams[conversation.id] = task

        provider_name, model = await self._selection(
            context, provider_name, model, conversation
        )

        try:
            if conversation is not None and conversations is not None:
                provider = await self._create_provider(context, provider_name)
                effective_query = await conversations.rewrite_query(
                    history, query, provider
                )
            else:
                effective_query = query

            search = await self._retrieval.search(
                context, effective_query, top_k=top_k, document_ids=document_ids
            )
            sources = [
                self._source_ref(item, number)
                for number, item in enumerate(search.items, start=1)
            ]
            yield {"type": "sources", "sources": [s.model_dump() for s in sources]}
            if is_disconnected and await is_disconnected():
                return

            diagnostics = {
                "rewritten_query": effective_query,
                "retrieval_ms": search.retrieval_ms,
                "reranked": search.reranked,
                "cache_hit": search.cache_hit,
                "chunks": [
                    {
                        "chunk_id": str(item.chunk_id),
                        "filename": item.filename,
                        "page_number": item.page_number,
                        "dense_rank": item.dense_rank,
                        "lexical_rank": item.lexical_rank,
                        "rrf_score": item.rrf_score,
                        "rerank_score": item.rerank_score,
                        "score": item.score,
                    }
                    for item in search.items
                ],
            }
            if not search.answerable or not search.items:
                final_text = "I don't know"
                confidence_result = await compute_answer_confidence(
                    answer=final_text,
                    answerable=False,
                    search_items=search.items,
                    valid_source_numbers=set(),
                )
                yield {"type": "token", "text": final_text}
                yield {
                    "type": "confidence",
                    "confidence_score": confidence_result.score,
                    "confidence_level": confidence_result.level,
                    "confidence_breakdown": confidence_result.breakdown,
                    "retrieval_diagnostics": diagnostics,
                }
                yield {
                    "type": "done",
                    "answer": final_text,
                    "citations": [],
                    "answerable": False,
                    "conversation_id": conversation_id,
                    "provider": provider_name,
                    "model": model,
                }
                return

            built = build_context(search.items, settings.prompt_context_token_budget)
            if not built.sources:
                final_text = "I don't know"
                yield {"type": "token", "text": final_text}
                yield {
                    "type": "done",
                    "answer": final_text,
                    "citations": [],
                    "answerable": False,
                    "conversation_id": conversation_id,
                    "provider": provider_name,
                    "model": model,
                }
                return

            messages = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
            if conversation is not None and conversations is not None:
                for item in conversations.truncate_history(history):
                    if item.role in ("user", "assistant"):
                        messages.append(
                            ChatMessage(role=item.role, content=item.content)
                        )
            messages.append(
                ChatMessage(
                    role="user",
                    content=f"Question: {effective_query}\n\n{built.text}",
                )
            )
            prompt_text = "\n".join(message.content for message in messages)
            if provider is None:
                provider = await self._create_provider(context, provider_name)
            if (
                conversation is not None
                and conversations is not None
                and not history
                and conversation.title == "New conversation"
            ):
                new_title = await conversations.generate_title(query, provider)

            started = time.monotonic()
            stopped = False
            stream = provider.stream(
                messages,
                max_tokens=settings.chat_max_tokens,
                **_model_options(provider, "stream", model),
            )
            try:
                async for event in stream:
                    if is_disconnected and await is_disconnected():
                        stopped = True
                        break
                    if isinstance(event, TextDelta):
                        collected.append(event.text)
                        yield {"type": "token", "text": event.text}
                    elif isinstance(event, Usage):
                        usage = event
                    elif isinstance(event, Error):
                        raise RuntimeError(event.message)
            finally:
                aclose = getattr(stream, "aclose", None)
                if aclose:
                    await aclose()
                latency = int((time.monotonic() - started) * 1000)

            final_text = "".join(collected) or "I don't know"
            answerable = final_text != "I don't know"
            if stopped:
                return
            citations = [
                Citation(
                    number=item.number,
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    filename=item.filename,
                    page_number=item.page_number,
                    heading_path=item.heading_path,
                )
                for item in parse_citations(final_text, built.sources)
            ]
            confidence_result = await compute_answer_confidence(
                answer=final_text,
                answerable=answerable,
                search_items=search.items,
                valid_source_numbers={s.number for s in sources},
                context_text=built.text,
            )
            yield {
                "type": "confidence",
                "confidence_score": confidence_result.score,
                "confidence_level": confidence_result.level,
                "confidence_breakdown": confidence_result.breakdown,
                "retrieval_diagnostics": diagnostics,
            }
            yield {
                "type": "done",
                "answer": final_text,
                "citations": [
                    {
                        **item.model_dump(),
                        "chunk_id": str(item.chunk_id),
                        "document_id": str(item.document_id),
                    }
                    for item in citations
                ],
                "answerable": answerable,
                "tokens": {
                    "input": usage.input_tokens if usage else count_tokens(prompt_text),
                    "output": usage.output_tokens
                    if usage
                    else count_tokens(final_text),
                    "estimated": usage is None,
                },
                "conversation_id": conversation_id,
                "provider": provider_name,
                "model": model,
            }
        except asyncio.CancelledError:
            final_text = "".join(collected)
            raise
        except Exception as exc:
            final_text = "".join(collected)
            yield {"type": "error", "message": str(exc)}
        finally:
            if provider is not None:
                close = getattr(provider, "close", None)
                if close:
                    await close()
            if conversation is not None and conversations is not None:
                await self._persist(
                    conversations,
                    conversation,
                    query,
                    final_text or "I don't know",
                    provider_name,
                    citations,
                    usage,
                    latency,
                    new_title,
                    prompt_text,
                    answerable=final_text != "I don't know",
                    model=model,
                    confidence_score=(
                        confidence_result.score if confidence_result else None
                    ),
                    confidence_level=(
                        confidence_result.level if confidence_result else None
                    ),
                    confidence_breakdown=(
                        confidence_result.breakdown if confidence_result else None
                    ),
                    retrieval_diagnostics=diagnostics,
                )
            if conversation is not None:
                active_streams.pop(conversation.id, None)

    async def regenerate_last(
        self,
        context: WorkspaceContext,
        conversation_id: uuid.UUID,
        provider_name: str | None = None,
    ) -> ChatResponse:
        """Replace the last assistant answer with a fresh one (no new user turn)."""
        if self._conversations is None:
            raise RuntimeError("conversation support is not configured")
        conversations = self._conversations
        await conversations.get(context, conversation_id)
        history = await conversations.messages(context, conversation_id)
        user_turns = [item for item in history if item.role == "user"]
        if not user_turns:
            from services.exceptions import ConversationNotFoundError

            raise ConversationNotFoundError()
        query = user_turns[-1].content
        await conversations.delete_last_turn(conversation_id)
        return await self.answer(
            context,
            query,
            provider_name=provider_name,
            conversation_id=conversation_id,
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
            excerpt=getattr(item, "text", None),
            char_start=getattr(item, "char_start", None),
            char_end=getattr(item, "char_end", None),
            dense_rank=getattr(item, "dense_rank", None),
            lexical_rank=getattr(item, "lexical_rank", None),
            rrf_score=getattr(item, "rrf_score", None),
            rerank_score=getattr(item, "rerank_score", None),
        )
