# RAG project — research notes

## Overview
Monorepo (Turborepo + pnpm) with a Python FastAPI backend (`apps/api`) and a Next.js frontend (`apps/web`), plus shared TS packages (`packages/*`). Local infra via Docker Compose (Postgres+pgvector, Redis, MinIO, Ollama).

## Status (as of 2026-11-15)
Backend is scaffolding only: health + ping routes, structured JSON logging with request IDs, global exception handlers, CORS from env, async SQLAlchemy engine/session, Alembic (async, vector extension migration). No domain models, repositories, services, or RAG pipeline yet. Frontend is the default create-next-app template. Shared UI package present.

## Verified facts
- Embedding model: `embeddinggemma-2:440m` via Ollama.
- Embedding dimension: 768 (verified at runtime; `ollama show` reports 512 text encoder but served vector is 768).
- Ollama and model are installed locally; model responds to `/api/embed`.
- API type-checks clean (ruff + mypy), web builds (Next 16) and type-checks clean.
- Alembic runs offline and emits `CREATE EXTENSION IF NOT EXISTS vector`.
- Docker daemon responded slowly/unavailable during research; compose not exercised.

## Open decisions (docs/decisions.md)
- Key scope: per user vs per workspace (suggested: per user).
- CLI mode scope: local only, off by default, env flag (already reflected in settings `cli_mode_enabled`).

## Gaps / next steps
- Implement ORM models (documents, chunks, embeddings vector(768)), repositories, services.
- Add ingestion endpoint + worker (MinIO storage, chunking, embedding via Ollama).
- Add retrieval endpoint (pgvector similarity search) and RAG chat orchestration.
- Wire frontend to API; replace template page.
- Decide API key scoping and implement auth.
- Pin embedding dimension in schema/migrations (768).


## Production Upgrade (`upgrade` branch — 2026-11-25)
All 5 phases of the RAG Workspace Implementation Plan have been completed and verified on the `upgrade` branch. See the dedicated [`notes/`](./notes/README.md) folder for phase-by-phase engineering notes and [`apps/web/content/docs/upgrade.md`](./apps/web/content/docs/upgrade.md) for the live documentation page (`/docs/upgrade`):
- **Phase 1**: Calibrated cross-encoder reranking (`BAAI/bge-reranker-v2-m3`), Contextual Retrieval + Small-to-Big parent-document chunking, isolated `ingest-fast`/`ingest-ocr` ARQ queues with vision-LLM fallback, and multilingual `'simple'` FTS + `pg_trgm`.
- **Phase 2**: From-scratch RAG Eval Engine (`Recall@K`, `MRR`, `NDCG@K`, LLM-as-a-Judge faithfulness/relevancy/citation accuracy), live multi-signal Answer Confidence Score + SSE event, feedback-to-eval promotion endpoint, and threshold-gated eval CLI.
- **Phase 3**: 4-tier cognitive memory (`workspace_memories`, ARQ consolidation with conflict superseding, strict `<memory>`/`<context>` isolation) and Light GraphRAG (`entities`, `entity_edges`, RBAC-safe 2-hop recursive SQL CTE retrieval).
- **Phase 4**: Redis Pub/Sub cross-replica stream cancellation, RBAC-safe Redis query cache with TTL eviction, `TRUSTED_PROXY_CIDRS`, Resend/SMTP email invites, Research Mode query decomposition & cited `compare_documents`, and incremental GitHub Compare API sync.
- **Phase 5**: Split-screen interactive PDF/document citation viewer, live Confidence Badges, Retrieval Inspector Drawer, `/evals` Dashboard, `/memory` Manager UI, and updated OpenAPI schema.
