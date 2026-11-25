# Phase 3 — 4-Tier Cognitive Memory & Light GraphRAG Notes

## Prompt 3.1: 4-Tier Cognitive Memory (`22ee646`)
- **Changes**:
  - Migration `a1b2c3d4e5f6` and `apps/api/models/memory.py` add `workspace_memories` (`tier: semantic|episodic|procedural`, `status: active|superseded`, `superseded_by_id`, `confidence`, `embedding`).
  - Built `apps/api/services/memory.py` with CRUD, top-K retrieval + procedural rule injection, and conflict reconciler outputting `ADD`, `UPDATE` (superseding the prior row via `superseded_by_id`), `NOOP`, or `INVALIDATE`.
  - Built ARQ worker `consolidate_turn_memory` in `apps/api/workers/memory.py`.
  - Updated `apps/api/core/prompting.py` with `build_memory_block` and sanitized `<memory>` / `</memory>` inside `sanitize_context_text()` so untrusted `<context>` chunks can never poison `<memory>`.
  - Added CRUD REST API at `/api/v1/workspaces/{workspace_id}/memories`.
- **Verification**: `apps/api/tests/test_memory.py` verified `"We deploy on AWS ap-southeast-2"` -> `"We migrated to ap-south-1"` supersedes the old record cleanly, plus `<memory>`/`<context>` isolation and CRUD endpoints (12/12 passed).

## Prompt 3.2: Lightweight Postgres Knowledge Graph (`6cd013c`)
- **Changes**:
  - Migration `b2c3d4e5f6a7` and `apps/api/models/graph.py` add `entities` and `entity_edges` tables with workspace/canonical indexes.
  - Built `apps/api/services/graph.py` with triple extraction (`extract_triples`), entity upsert (`index_document_chunks`), and permission-aware 1–2 hop recursive SQL CTE lookup (`find_2hop_chunks`) joined against `documents` and filtered by `DocumentGrant` `allowed_document_ids`.
  - Wired entity indexing into `apps/api/workers/ingest.py` and 2-hop candidate fusion into `apps/api/services/retrieval.py` before reranking.
- **Verification**: `apps/api/tests/test_graph.py` verified 2-hop discovery across `"Service A calls Auth API"` and `"Auth API uses Redis 7"`, while confirming restricted documents never leak to unauthorized members (14/14 passed).
