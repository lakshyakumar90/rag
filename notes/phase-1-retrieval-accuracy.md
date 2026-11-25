# Phase 1 — Retrieval Accuracy & Ingestion Pipeline Notes

## Prompt 1.1: Calibrated RRF Threshold & Cross-Encoder Reranking (`d0d9bd6`)
- **Problem Fixed**: Raw RRF scores with `k=60` peak at `2/61 ≈ 0.0328`, making a naive `0.15` threshold on raw RRF miscalibrated, while normalized rank-1 RRF (`1.0`) failed to reject weak off-topic cosine matches.
- **Changes**:
  - Added self-hosted HuggingFace TEI `reranker` service (`BAAI/bge-reranker-v2-m3`) to `docker-compose.yml` under profile `reranker`.
  - Added `rerank_threshold=0.35`, `retrieval_cosine_threshold=0.25`, and `retrieval_rrf_min_score=0.012` in `apps/api/core/config.py`.
  - Added sigmoid calibration safeguard in `apps/api/providers/rerank.py`.
  - Preserved `dense_rank`, `lexical_rank`, `dense_score`, `lexical_score`, `rrf_score`, `rerank_score`, and `retrieval_ms` across `core/rrf.py`, `repositories/retrieval.py`, `schemas/retrieval.py`, and `services/retrieval.py`.
- **Verification**: `apps/api/tests/test_retrieval.py` (12/12 passed), including on-topic vs off-topic gating both with and without the reranker enabled.

## Prompt 1.2: Contextual Retrieval & Small-to-Big Parent-Document Chunking (`d5fd3ba`)
- **Changes**:
  - Migration `c9e1f3a57b2d` adds `parent_content`, `context_header`, `char_start`, and `char_end` to `document_chunks`.
  - Implemented `chunk_hierarchical` in `apps/api/workers/chunking.py` (~1,000-token parent windows, ~250-token child chunks linked via `parent_text`).
  - Added `generate_context_header` in `apps/api/workers/ingest.py` (with LLM + deterministic structural fallback) prepended to child text before embedding and FTS indexing.
  - Updated `build_context` in `apps/api/core/prompting.py` to pack deduplicated `parent_content` within the 2,000-token budget while preserving exact child `[n]` citations.
- **Verification**: `apps/api/tests/test_contextual_retrieval.py` + `test_chunking.py` + `test_prompting.py` + `test_worker.py` (53/53 passed).

## Prompt 1.3: Isolated OCR Queue, Vision Fallback & Multilingual FTS (`6a4a04c`)
- **Changes**:
  - Split ARQ queues in `apps/api/providers/queue.py` and `apps/api/workers/settings.py` into `ingest-fast` (`FastWorkerSettings`) and `ingest-ocr` (`OcrWorkerSettings`, bounded concurrency + `mem_limit: 2g` in `docker-compose.yml`).
  - Added `is_scanned_pdf` heuristic in `apps/api/workers/ocr.py` to route scanned PDFs to `ingest-ocr` while TXT/MD/DOCX/text PDFs finish immediately on `ingest-fast`.
  - Added Tesseract mean word confidence calculation (`ocr_page_detailed`) with vision-LLM Markdown fallback when confidence drops below `ocr_min_confidence=65.0`.
  - Migration `d1e2f3a4b5c6` switches `document_chunks.search_vector` to `'simple'` FTS + `pg_trgm` GIN index, and `repositories/retrieval.py` queries both `websearch_to_tsquery('simple', :query)` and `similarity(dc.content, :query) > 0.15`.
- **Verification**: `apps/api/tests/test_ocr.py`, `test_worker.py`, `test_retrieval.py`, `test_documents.py` (43/43 passed).
