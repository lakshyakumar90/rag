# Phase 2 — Evaluation Engine, Live Confidence & CI Gate Notes

## Prompt 2.1: From-Scratch RAG Evaluation Engine (`cbf2907`)
- **Changes**:
  - Migration `e2f3a4b5c6d7` and `apps/api/models/evals.py` add `eval_datasets`, `eval_cases`, `eval_runs`, and `eval_results`.
  - Built `apps/api/services/evals.py` with:
    - Pure-Python retrieval metrics: `compute_recall_at_k`, `compute_mrr`, `compute_ndcg_at_k`.
    - From-scratch LLM-as-a-Judge metrics (strict JSON output with deterministic lexical fallback): `evaluate_faithfulness`, `evaluate_answer_relevancy`, and `evaluate_citation_accuracy`.
  - Added async ARQ job `run_eval_suite` in `apps/api/workers/evals.py`.
  - Exposed REST API under `/api/v1/workspaces/{workspace_id}/evals/*` in `apps/api/api/v1/endpoints/evals.py`.
- **Verification**: `apps/api/tests/test_evals.py` (passed end-to-end).

## Prompt 2.2: Live Answer Confidence Score & Feedback Flywheel (`fbfc72b`)
- **Changes**:
  - Migration `f3a4b5c6d7e8` adds `confidence_score`, `confidence_level` (`high|medium|low`), `confidence_breakdown`, and `retrieval_diagnostics` to `messages`.
  - Built `apps/api/services/confidence.py` combining top rerank/retrieval score, sentence citation coverage ratio, and optional faithfulness check.
  - Emitted a `confidence` SSE event in `apps/api/services/chat.py` before `done`, persisting both confidence and retrieval diagnostics on assistant messages.
  - Added `POST /api/v1/workspaces/{workspace_id}/messages/{message_id}/promote-to-eval` so admins can turn thumbs-down chat answers into regression `EvalCase` rows in one click.
- **Verification**: `apps/api/tests/test_confidence.py`, `test_prompting.py`, `test_streaming_chat.py` (16/16 passed).

## Prompt 2.3: CI Eval Regression Gate (`1236d01`)
- **Changes**:
  - Updated `evals/evaluate.py` with `--fast`, `--markdown` (writes to `$GITHUB_STEP_SUMMARY`), `--fail-under-recall`, `--fail-under-faithfulness`, and `--fail-under-citation` flags returning non-zero exit code on regression.
  - Added GitHub Actions workflow template at `evals/ci/evals.workflow.yml`.
- **Verification**: Ran `evals/evaluate.py --fast --markdown` locally (`Recall@5: 1.00`, `Faithfulness: 0.83`, `Citation Acc: 0.92`) and confirmed exit code `0` at `0.80` floor and exit code `1` at `0.85` floor.
