# End-to-end tests (Playwright)

These tests drive the real UI against a running API, Postgres, Redis, MinIO and
ingestion worker. They are intentionally separate from the unit/type checks.

## One-time setup

```bash
# from the repo root
pnpm install --no-frozen-lockfile   # installs @playwright/test (web devDependency)
pnpm --filter web exec playwright install chromium
```

The web app must be served on `http://localhost:3000` (override with
`E2E_BASE_URL`) and the API on `http://localhost:8000` (`NEXT_PUBLIC_API_BASE_URL`
is read at build time). Start the stack with `docker compose up -d` plus the API
and worker, then build/serve the web app:

```bash
pnpm --filter web build && pnpm --filter web start
```

## Run

```bash
pnpm --filter web e2e
# a single spec
pnpm --filter web exec playwright test --config e2e/playwright.config.ts e2e/signup.spec.ts
```

## Coverage

- `signup.spec.ts` — account creation, dashboard redirect, weak-password error.
- `upload.spec.ts` — upload reaches `ready`, documents stay inside their workspace.
- `chat.spec.ts` — a question produces an assistant turn; feedback can be saved.

Each test creates a unique user with `Date.now()` so runs do not collide. The
chat tests tolerate an "I don't know" answer because a local environment may
have no LLM provider configured; they assert the grounded pipeline produced an
assistant message rather than a specific answer.
