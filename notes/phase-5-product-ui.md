# Phase 5 — Product-Grade UI Overhaul Notes

## Prompt 5.1: Split-Screen Interactive PDF/Document Citation Viewer & Confidence Badges (`60c47f1`)
- **Changes**:
  - Exported the updated FastAPI OpenAPI spec (`apps/web/lib/api/openapi.json`, 205 KB) covering all Phase 1–4 endpoints and diagnostic fields.
  - Extended `apps/web/lib/chat-stream.ts` to parse the live `"confidence"` SSE event (`confidence_score`, `confidence_level`, `confidence_breakdown`, `retrieval_diagnostics`).
  - Built `apps/web/components/confidence-badge.tsx` showing color-coded `High / Medium / Low` badges with hover/click breakdown popovers.
  - Built `apps/web/components/citation-split-viewer.tsx` rendering an interactive split-screen pane with PDF `#page=N` viewer toggle, Markdown/code highlighted source passage, heading breadcrumbs, character offsets, and per-chunk retrieval diagnostics (`Rerank`, `RRF`, `Dense #`, `Lexical #`).

## Prompt 5.2: Retrieval Inspector Drawer, Evals Dashboard & Memory Manager UI (`da5a4a8`)
- **Changes**:
  - Built `apps/web/components/retrieval-inspector-drawer.tsx` showing rewritten query, cache hit/miss, rerank mode, retrieval latency (`ms`), and a per-chunk diagnostic table.
  - Built `/workspaces/[workspaceId]/evals` (`apps/web/app/workspaces/[workspaceId]/evals/page.tsx`) with dataset manager, case builder, "Run Eval" trigger, KPI cards (`Recall@5`, `Faithfulness`, `Answer Relevancy`, `Citation Accuracy`), run history table, and failure drilldown.
  - Built `/workspaces/[workspaceId]/memory` (`apps/web/app/workspaces/[workspaceId]/memory/page.tsx`) with tabbed views for **Semantic Facts** (with active/superseded lineage toggle), **Episodic Summaries**, and **Procedural Rules** (inline add/edit/delete).
  - Updated `apps/web/components/app-shell.tsx` navigation to link directly to **Evals** and **Memory**, added typed API methods in `apps/web/lib/api/client.ts`, wired all components into `chat/page.tsx`, and added Playwright smoke checks in `apps/web/e2e/upgrade-ui.spec.ts`.
