# RAG Workspace — Production Upgrade Engineering Notes (`upgrade` branch)

This folder documents every engineering deliverable completed on the `upgrade` branch across all 5 phases of the RAG Workspace upgrade plan.

## Phase Index

| Phase | Scope | Commit(s) | Detailed Notes |
| :--- | :--- | :--- | :--- |
| **Phase 1** | Retrieval Accuracy (Reranker, Contextual Retrieval, OCR Queue & Multilingual FTS) | `d0d9bd6`, `d5fd3ba`, `6a4a04c` | [Phase 1 Notes](./phase-1-retrieval-accuracy.md) |
| **Phase 2** | From-Scratch Eval Engine, Live Answer Confidence & CI Regression Gate | `cbf2907`, `fbfc72b`, `1236d01` | [Phase 2 Notes](./phase-2-evals-confidence-ci.md) |
| **Phase 3** | 4-Tier Cognitive Memory & Lightweight Postgres Knowledge Graph | `22ee646`, `6cd013c` | [Phase 3 Notes](./phase-3-cognitive-memory-graphrag.md) |
| **Phase 4** | Multi-Replica Redis Scaling, RBAC-Safe Cache, Email Invites & Research Agent | `fd5cea5`, `4011ce3` | [Phase 4 Notes](./phase-4-scaling-and-agents.md) |
| **Phase 5** | Product-Grade UI Overhaul (Split Citation Viewer, Inspector, Evals & Memory UI) | `60c47f1`, `da5a4a8` | [Phase 5 Notes](./phase-5-product-ui.md) |

## Database Migrations Added (Alembic Chain)

All migrations chain linearly from the pre-upgrade head `b8d0e2f14a6c`:

1. `c9e1f3a57b2d` — Add `parent_content`, `context_header`, `char_start`, `char_end` to `document_chunks`.
2. `d1e2f3a4b5c6` — Switch `document_chunks.search_vector` to multilingual `'simple'` FTS + `pg_trgm` GIN index.
3. `e2f3a4b5c6d7` — Add `eval_datasets`, `eval_cases`, `eval_runs`, `eval_results`.
4. `f3a4b5c6d7e8` — Add `confidence_score`, `confidence_level`, `confidence_breakdown`, `retrieval_diagnostics` to `messages`.
5. `a1b2c3d4e5f6` — Add `workspace_memories` table for 4-tier cognitive memory.
6. `b2c3d4e5f6a7` — Add `entities` and `entity_edges` tables for Light GraphRAG.

## Important Operational Note (GitHub Actions Workflow)

The threshold-gated GitHub Actions workflow is stored at `evals/ci/evals.workflow.yml` because the GitHub Personal Access Token used during the upgrade push did not include the `workflow` OAuth scope. To activate the CI workflow on GitHub, copy it into place locally:

```bash
cp evals/ci/evals.workflow.yml .github/workflows/evals.yml
git add .github/workflows/evals.yml
git commit -m "ci(evals): activate GitHub Actions eval regression workflow"
```
