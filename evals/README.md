# RAG evaluation

A rerunnable, fully local evaluation of the retrieval and grounded-answer
pipeline. No API keys, network calls, Docker or Postgres are required: the
harness builds a fresh in-memory SQLite workspace for every configuration.

## Run

```bash
# from the repo root, using the project virtualenv
.venv/Scripts/python.exe evals/evaluate.py
# or
pnpm eval
```

It prints a comparison table and rewrites `evals/results.json`.

## Layout

- `corpus/*.txt` — five department documents, 15 pages total. Pages are marked
  with `=== PAGE n ===` so expected source pages are unambiguous.
- `questions.jsonl` — 42 questions. Each row has `id`, `question`,
  `answerable`, and for answerable questions `expected_answer`, `expected_doc`
  and `expected_pages`.
- `evaluate.py` — the harness.
- `results.json` — generated output; commit it after a change so results can be
  compared over time.

## What is exercised

Real application code: `chunk_document`, `RetrievalRepository.vector_search`,
`RetrievalRepository.keyword_search`, `reciprocal_rank_fusion`,
`RetrievalService._rerank`, `build_context`, `ChatService.answer` and
`parse_citations`.

Deterministic local stand-ins (replace these for a production score):

| Component | Stand-in | Swap in |
|---|---|---|
| Embeddings | `HashingEmbedder` (signed feature hashing) and corpus-fitted `TfidfEmbedder` | `providers.embeddings.get_embedding_provider` |
| Reranker | `LexicalReranker` (term overlap) | `providers.rerank.Reranker` |
| Answer generation | `ExtractiveLLM` (best matching context sentence + `[n]`) | `create_llm_provider` |

The harness patches `services.chat.create_llm_provider` only; the rest of the
answer path is unchanged. Answer correctness is therefore a measure of whether
the right evidence reached the context and was cited, not of a real LLM's
fluency.

## Metrics

- `hit@k` — share of answerable questions with at least one of the top-k
  chunks from the expected document **and** expected page (page-level hit).
- `answer_correctness` — share of answerable answers containing the normalized
  expected answer string.
- `citation_accuracy` — share of answerable questions with at least one
  citation to the expected document and page.
- `idk_accuracy` — share of unanswerable questions answered exactly
  "I don't know".
- `false_idk_rate` — share of answerable questions answered "I don't know".

## Comparison matrix

Chunk sizes 128/256/512 tokens (20% overlap) × three embedders × vector-only vs
hybrid × reranking off/on = 36 runs of all 42 questions.

See `docs/evaluation.md` for the recorded results and interpretation.
