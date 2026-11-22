## Candidate generation and ranking

The retrieval service checks workspace and document access before evidence is used. It can rewrite a follow-up into a standalone search query, embed it with the workspace's active profile, and search Qdrant when enabled. PostgreSQL keyword ranking supplies candidates for exact phrases or terms. For compatible profiles, pgvector can serve a configured fallback. PostgreSQL resolves vector candidates back to readable, ready chunks.

Reciprocal rank fusion merges the candidate lists without requiring matching score scales. Optional reranking can reorder the fused list when a supported reranker is configured. Higher rank indicates relative ordering. Answerability also depends on evidence quality and threshold configuration.

## Prompting and citations

`core/prompting.py` numbers the selected chunks, attaches references and assembles a bounded evidence context. Retrieved text is treated as untrusted content. Copying arbitrary text into evidence can still influence a model, so citations and source inspection are part of the answer workflow.

The chat endpoint sends server-sent events with source metadata, answer tokens, completion, and errors. The UI parses events in `lib/chat-stream.ts`, renders citation controls and opens the referenced excerpts. The conversation history persists in PostgreSQL. Streaming stop state is process-local, which matters if you add multiple API replicas.

## Caching and language coverage

`services/query_cache.py` stores exact retrieval results and supports a configurable semantic cache. Exact caching is enabled by default. If varying top-k for the same query matters to an experiment, disable caching because the exact key omits requested top-k. Semantic cache is off by default. Its similarity lookup does not distinguish document scopes, so keep it disabled for document-scoped comparisons. Test cache behavior after permission, document and embedding-profile changes.

A multilingual embedding profile can improve cross-language vector matching. Keyword search also depends on the configured text-search behavior and OCR on installed language packs. Run the multilingual evaluation against representative documents before relying on comparable quality across languages.
