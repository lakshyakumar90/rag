---
version: 1
slug: "apps-web-app-page-tsx"
primary_target: "apps/web/app/page.tsx"
related_targets: ["apps/web/app/workspaces/[workspaceId]/chat/page.tsx","apps/web/app/workspaces/[workspaceId]/documents/page.tsx"]
---

Scope: Operate — the authenticated RAG workspace (dashboard, documents, chat, members, settings, auth).

Audience: developers and small teams doing long, repeatable document-review sessions at a desk, sometimes on a phone. Job: get a grounded answer and verify its source. Proof: real uploaded documents, real streamed tokens, real citation chips. Constraints: pure black dark / off-white light, minimal, developer-console structure with editorial restraint, responsive to 320px.

## Direction contract

THESIS: A quiet instrument panel for evidence, not a marketing dashboard. The category default is a grid of equal cards with a hero metric; this refuses it — one dense work surface, a single signal color, and the source always within reach.

OWN-WORLD: Pure black (#000) in dark, warm off-white (#FAF9F6) in light. One neutral family, one hairline border, one blue signal used only for active state, primary action and focus. Geist Sans for interface, Geist Mono for identifiers, sizes and code. 10px radii, 12px row insets, no decorative shadows; one elevated panel for the citation drawer.

STORY: The visitor lands in a workspace, sees documents move from queued to ready, asks a question, watches the answer arrive token by token, and opens [1] to read the exact chunk. Everything else is secondary.

FIRST VIEWPORT: A 220px left rail (workspace switcher, four nav items, user menu) beside a single main column with a thin top bar. The main column leads with the current task's content, not a card grid. On mobile: a sticky top bar with switcher and a bottom tab bar; the rail becomes a drawer.

FORM: Minimal developer console with editorial spacing — chosen from the user-pinned direction; concept roll skipped because the direction is pinned. SEED: pinned-by-user.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.
