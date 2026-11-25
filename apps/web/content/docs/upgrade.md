# Production Upgrade (v2)

The `upgrade` release elevates RAG Workspace from a baseline hybrid-search chatbot into a full-grade, observable, multi-replica knowledge-work system. Every capability below is backed by database migrations, automated tests, and UI surfaces.

## Phase 1: Retrieval Accuracy & Ingestion Isolation

### Calibrated Cross-Encoder Reranking & Abstention Gate
Raw Reciprocal Rank Fusion (`k=60`) peaks at `2/61 ≈ 0.0328`. The upgraded retrieval pipeline (`apps/api/services/retrieval.py`) fixes abstention gating in two ways:
- **Cross-Encoder Mode (`RERANK_ENABLED=true`)**: Fuses top-20 dense + top-20 lexical candidates via RRF, passes them through the self-hosted HuggingFace TEI reranker (`BAAI/bge-reranker-v2-m3` in `docker-compose.yml`), calibrates scores into `[0, 1]`, and gates `answerable` on `RERANK_THRESHOLD=0.35`.
- **Fallback Mode**: When reranking is disabled or unreachable, gates on calibrated raw cosine similarity (`RETRIEVAL_COSINE_THRESHOLD=0.25`) or lexical hits combined with a raw RRF floor (`RETRIEVAL_RRF_MIN_SCORE=0.012`).
- Every `SearchResult` exposes `dense_rank`, `lexical_rank`, `rrf_score`, `rerank_score`, and `retrieval_ms`.

### Contextual Retrieval & Small-to-Big Chunking
- **Hierarchical Chunking (`CHUNKING_STRATEGY=hierarchical`)**: Splits sections into ~1,000-token parent windows and ~250-token child chunks (`parent_content`, `char_start`, `char_end`).
- **Contextual Headers (`CONTEXTUAL_RETRIEVAL_ENABLED=true`)**: Generates a 1–2 sentence context header (`context_header`) prepended to each child chunk before embedding and FTS indexing.
- **Deduplicated Parent Packing**: `core/prompting.py` packs full `parent_content` into `<context>` (deduplicated across sibling children sharing the same parent window) within the 2,000-token budget while preserving exact child `[n]` citations.

### Isolated OCR Queue, Vision Fallback & Multilingual FTS
- **Queue Isolation**: ARQ workers are split into `ingest-fast` (`FastWorkerSettings`) for TXT/MD/DOCX/text PDFs and `ingest-ocr` (`OcrWorkerSettings`, bounded concurrency + `mem_limit: 2g`) for scanned PDFs.
- **Vision-LLM Fallback**: `workers/ocr.py` computes Tesseract mean word confidence per page; pages below `OCR_MIN_CONFIDENCE=65.0` fall back to a configured vision-capable model (`OCR_VISION_MODEL`) for Markdown table/chart extraction.
- **Multilingual FTS + Trigrams**: `document_chunks.search_vector` uses PostgreSQL `'simple'` configuration plus a `pg_trgm` GIN index so non-English text and code identifiers match reliably.

## Phase 2: From-Scratch Eval Engine, Live Confidence & CI Gate

### From-Scratch Evaluation Engine
- **Tables**: `eval_datasets`, `eval_cases`, `eval_runs`, `eval_results`.
- **Pure-Python Retrieval Metrics**: `Recall@K`, `MRR`, and `NDCG@K`.
- **LLM-as-a-Judge Metrics**: `faithfulness` (atomic claim decomposition & support check), `answer_relevancy`, and `citation_accuracy` (verifying `[n]` markers against cited source chunks) with strict JSON parsing.
- **REST API**: `/api/v1/workspaces/{workspace_id}/evals/datasets`, `/cases`, `/runs`, `/runs/{run_id}` + async ARQ task `run_eval_suite`.

### Live Answer Confidence & Feedback Flywheel
- `apps/api/services/confidence.py` computes a multi-signal score combining top rerank/retrieval score, sentence citation coverage ratio, and optional faithfulness verification, persisted on `messages` (`confidence_score`, `confidence_level`, `confidence_breakdown`) and streamed via a `confidence` SSE event.
- Admins can promote any thumbs-down answer into a regression test case via `POST /api/v1/workspaces/{workspace_id}/messages/{message_id}/promote-to-eval`.

### Threshold-Gated Eval CLI
Run locally or in CI (`evals/ci/evals.workflow.yml`):
```bash
python evals/evaluate.py --fast --markdown \
  --fail-under-recall 0.80 \
  --fail-under-faithfulness 0.80 \
  --fail-under-citation 0.80
```

## Phase 3: 4-Tier Cognitive Memory & Light GraphRAG

### 4-Tier Cognitive Memory
- Stored in `workspace_memories` across three persistent tiers (`semantic`, `episodic`, `procedural`) with `active` / `superseded` status and `superseded_by_id` lineage.
- Async ARQ job `consolidate_turn_memory` reconciles candidate facts with `ADD`, `UPDATE` (superseding prior contradictory facts), `NOOP`, or `INVALIDATE`.
- Prompting strictly isolates trusted `<memory>` from untrusted `<context>` document chunks so document prompt injections cannot poison workspace memory.
- Full CRUD API at `/api/v1/workspaces/{workspace_id}/memories`.

### Lightweight Postgres Knowledge Graph (Light GraphRAG)
- `entities` and `entity_edges` tables store extracted `(source, relation, target)` triples per document/chunk without operating a separate Neo4j cluster.
- `services/graph.py` executes a permission-aware 1–2 hop recursive SQL CTE filtered by `DocumentGrant` `allowed_document_ids`, merging graph-linked chunks into hybrid RRF fusion before reranking.

## Phase 4: Multi-Replica Scaling & Research Agent Workflows

- **Redis Pub/Sub Stream Cancellation**: `chat:cancel:<stream_id>` cancels active SSE generations across any FastAPI replica.
- **RBAC-Safe Redis Query Cache**: Exact keys include `(workspace_id, auth_scope_hash, doc_filter_hash, top_k, profile_id, query_hash)` with Redis TTL eviction (`300s`) and partitioned semantic buckets so restricted documents never leak across users.
- **Trusted Proxy CIDRs & Email Invites**: `TRUSTED_PROXY_CIDRS` protects `X-Forwarded-For` IP rate limiting behind load balancers, and `services/invitations.py` delivers invite links via Resend or SMTP.
- **Research Mode & Incremental GitHub Sync**: Agent step budget increased to `8` with `decompose_query`, cited `compare_documents`, `self_critique_answer`, and GitHub Compare API incremental sync (`last_synced_commit_sha`).

## Phase 5: Product-Grade UI Overhaul

- **Split-Screen Citation Viewer** (`components/citation-split-viewer.tsx`): Clicking `[1]`, `[2]` opens a split pane with PDF `#page=N` view, highlighted Markdown/code excerpts, heading breadcrumbs, and per-chunk retrieval scores.
- **Live Confidence Badges** (`components/confidence-badge.tsx`): Displays `High / Medium / Low` confidence pills with breakdown popovers on every assistant message.
- **Retrieval Inspector Drawer** (`components/retrieval-inspector-drawer.tsx`): Shows rewritten query, cache hit/miss, rerank status, latency, and per-chunk dense/lexical/RRF/rerank scores.
- **Evals Dashboard** (`/workspaces/[id]/evals`) and **Memory Manager** (`/workspaces/[id]/memory`) linked directly in the workspace sidebar.
