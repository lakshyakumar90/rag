# Architecture and tradeoffs

This document explains *why* the app is shaped the way it is. For the chronological record see [decisions.md](decisions.md), for quality numbers see [evaluation.md](evaluation.md), and for operational procedures see [backup.md](backup.md). The short version: a local-first FastAPI + Next.js RAG app where correctness of tenant boundaries, grounded answers and reproducible tests mattered more than feature breadth.

## Monorepo and task orchestration

**Choice:** one repository managed by Turborepo, with pnpm for the TypeScript workspace and uv for Python. `turbo.json` defines `build`, `lint`, `check-types` and `dev`; the API is *not* a pnpm package, so Python commands live in `pyproject.toml` and CI invokes them directly.

**Given up:** a single language/toolchain and the convenience of one install command. Python and JS dependencies are locked separately (`uv.lock`, `pnpm-lock.yaml`).

**Revisit:** if the API is ever rewritten in TypeScript, collapse to one lockfile. Until then, keep the two verification tracks explicit in CI.

## FastAPI service boundaries

**Choice:** thin HTTP routes under `api/v1/endpoints/`, business logic in `services/`, data access in `repositories/`, ORM in `models/`, request/response DTOs in `schemas/`. Services raise typed `DomainError` subclasses; a single handler in `core/exceptions.py` maps them to the app's `{ "error": ... }` JSON envelope. Dependencies in `api/v1/dependencies.py` resolve the current user, workspace context and service instances.

**Why:** services stay framework-agnostic and testable without an HTTP client, while error mapping is defined once. Adding a new endpoint is mostly wiring.

**Given up:** some indirection — a one-line endpoint may touch four directories — and strict typing at the repository boundary is conventional rather than generated.

**Revisit:** if a service grows a second caller (for example a CLI or an event consumer), that is a signal to promote it to a proper application module rather than adding HTTP-specific branches.

## SQLite in tests, Postgres + pgvector in production

**Choice:** tests run against an in-memory SQLite database (`aiosqlite`) with a fake Redis. Custom SQLAlchemy types make this possible: `VectorType` emits `vector(768)` on Postgres and JSON on SQLite; `TSVectorType` emits `TSVECTOR` and a generated `search_vector` column on Postgres but a plain lowercase token string on SQLite. Retrieval falls back to Python cosine similarity over JSON vectors and token overlap for keyword search. A separate integration suite (`test_postgres_integration.py`) runs real Alembic migrations against `TEST_DATABASE_URL` or a `pgvector/pgvector:pg16` testcontainer, and skips cleanly when neither is available.

**Why:** the dominant test suite is fast and dependency-free — contributors can run `uv run pytest -q` without Docker — while the small integration suite still proves pgvector distance, `tsvector`, `SET NULL` audit FKs and cascade behavior on the real engine.

**Given up:** SQLite paths are not the production paths. Source-level SQL assertions cover the generated HNSW/cosine and GIN/tsvector indexes, but a SQL regression can in principle slip past a SQLite-only test run.

**Revisit:** make the Postgres integration suite mandatory in every CI job if a cheap service container remains available; treat a green SQLite-only run as a fast signal, not a release gate.

## Chunking and heading paths

**Choice:** three strategies in `workers/chunking.py`, all returning the same `Chunk` shape (text, index, page number, heading path, token count):

- `fixed` — ~500-token windows with 50-token overlap over exact source slices, so original text is preserved.
- `paragraph` — packs short paragraphs whole, splits long ones at sentence boundaries, and falls back to windows for oversized sentences.
- `heading` — the same packer, but tracks a heading stack from Markdown ATX headings and DOCX `Heading N` styles and stores the path as JSON.

`auto` (the default) uses `heading` when a document has heading paths and `paragraph` otherwise. Token counting uses a deterministic offline regex tokenizer (words/numbers/punctuation count once; each CJK or emoji code point counts once) instead of a model vocabulary.

**Why:** one chunk contract lets the embedder, retrieval and UI stay unaware of the strategy. Heading paths improve citations ("page 4 › Expenses › Travel"), and the offline tokenizer keeps counts stable across machines.

**Given up:** token counts are approximate relative to the actual embedding model, and scanned PDFs have no heading structure to exploit.

**Revisit:** switch to the provider's real tokenizer when a single embedding model is pinned for production; evaluation currently favors 256 tokens with 20% overlap over the 500-token default for this document profile ([evaluation.md](docs/evaluation.md)).

## Hybrid retrieval, RRF and the abstention problem

**Choice:** vector search uses `1 - (embedding <=> :vector)` cosine distance against a partial HNSW index (`vector_cosine_ops`); keyword search uses `websearch_to_tsquery('english', :query)` with `ts_rank_cd` over a generated `search_vector` and a GIN index. Both are filtered by `workspace_id`, `ready` status and non-null vectors. Results are fused with reciprocal rank fusion, `1 / (k + rank)` with `k = 60`, normalized by the best achievable single-list rank-1 score. An optional TEI-compatible `/rerank` hook can reorder the fused list; failures fall back to fused order.

**Why:** hybrid retrieval covers both paraphrase and exact-term questions, and RRF avoids having to calibrate cosine scores against BM25-style scores. The normalization was added so a configured threshold would be meaningful.

**Given up / known defect:** it isn't. The [evaluation](docs/evaluation.md) found that RRF maps rank 1 to exactly 1.0 and rank 5 to about 0.94, so `RETRIEVAL_SCORE_THRESHOLD = 0.15` is satisfied whenever *any* chunk is returned. Across all 36 runs, `idk_accuracy` and `false_idk_rate` were both 0.000 — the abstention logic never fires. The UI still shows "I don't know" when retrieval is explicitly marked not answerable, but low confidence cannot currently be inferred from the fused score.

**Revisit:** apply a calibrated relevance threshold to the *pre-fusion* candidate scores or add a separate evidence check, then re-run the harness to obtain a meaningful "I don't know" baseline. That is the highest-value retrieval fix.

## Prompting, citations and injection defense

**Choice:** the system prompt says to answer only from `<context>`, reply exactly "I don't know" when evidence is missing, and cite every claim with `[n]`. The context builder numbers sources 1..N with document/page/heading metadata, fits `PROMPT_CONTEXT_TOKEN_BUDGET` (2000), strips control characters, escapes delimiter tags and flags truncation. `[n]` references in the answer are parsed and mapped back to chunk/document ids. The chat service skips the LLM entirely when retrieval is not answerable.

**Why:** citations are the product's trust surface, and escaped delimiters keep a document from forging a closing tag or instructions.

**Given up:** citations are parsed out of free text, not stored as a first-class relation; analytics must read the `Message.citations` JSON, and ambiguous "[30 days]" style numbers in two documents can produce the wrong source ([evaluation.md](docs/evaluation.md#findings)).

**Revisit:** introduce a normalized citation table when analytics outgrow JSON scanning or citation accuracy becomes a release blocker.

## Streaming chat: SSE, stop and regenerate

**Choice:** `POST /workspaces/{id}/chat` streams `data:` frames with types `sources`, `token`, `done` and `error`; the non-streaming equivalent is `POST /chat/complete`. The generator persists both user and assistant turns in a `finally` block, so a client disconnect still saves the partial answer while the `done` frame is suppressed. `POST /conversations/{id}/stop` cancels a generation through an in-process registry keyed by conversation id; `POST /conversations/{id}/regenerate` deletes the last turn and generates again. Token usage comes from the provider when available, otherwise from the offline tokenizer with `tokens_estimated = true`.

**Why:** streaming makes long answers feel responsive, and the `finally`-based persistence avoids lost conversations on navigation or network failure.

**Given up / known limitation:** stop/cancellation state is local to one API process. With multiple replicas, a `/stop` request can land on a different process than the one streaming and will do nothing. The client reconnects only once, before any token is emitted, because the backend has no replayable event ids.

**Revisit:** move active-generation tracking into Redis (keyed by conversation id with a pub/sub cancel channel) and add event ids before running more than one API replica.

## BYOK encryption and SSRF guard

**Choice:** `ProviderConfig` stores `encrypted_api_key` and `key_last4` only. Encryption is Fernet with `LLM_MASTER_KEY`; the plaintext is never logged, returned or stored, `ProviderConfigResponse` has no key fields, and connection-test errors replace the secret with `***`. A missing or invalid master key returns 503. `core/net.py` accepts only http(s) URLs with a host and no embedded credentials, and blocks localhost, loopback, private, link-local and reserved IPs unless `LOCAL_MODE_ENABLED = true`.

**Why:** users can use their own provider accounts without the app becoming a credential store or an open proxy into the internal network.

**Given up:** DNS names are allowed without resolution checks, so DNS rebinding is not prevented here; guarding it is the responsibility of the production egress layer. Per-workspace provider selection is also deferred — configs are per user.

**Revisit:** resolve and pin addresses at request time if BYOK is exposed to untrusted tenants, and add per-workspace configs if teams need to share credentials.

## Authentication and session model

**Choice:** Argon2id password hashing with rehash-on-login; a password policy (8–128 characters with character classes and a small denylist) applied on registration and password change but not login, so old passwords remain usable after a policy change. Refresh tokens are stored only as SHA-256 hashes; JWTs carry a `type` claim separating access from refresh tokens. Rotation revokes the old row and inserts the replacement in one `FOR UPDATE` transaction, and reuse revokes the whole token family. Logout is idempotent; changing the password revokes all refresh tokens. Emails are normalized and uniqueness is enforced by a functional index plus `IntegrityError` handling. Login verifies against a dummy hash for unknown emails to equalize timing.

**Why:** the browser keeps the short-lived access token in module memory and the refresh token in an HttpOnly, Secure, SameSite cookie scoped to `/api/v1/auth`; the fetch wrapper retries once after a silent refresh on 401. This removes the two common token-theft paths (XSS reading `localStorage`, and refresh tokens in response bodies).

**Given up:** no email verification or mail-based password reset — invitations return a shareable accept link instead, because no mail transport is available locally.

**Revisit:** add a transactional email provider before any internet-facing deployment; keep the cookie flags as they are.

## Rate limiting

**Choice:** two deliberately different failure modes.

- **Metered actions (fail closed).** `UserRateLimiter` keeps one Redis counter per user and action (`ratelimit:user:{id}:{chat|upload}`), incremented by an `INCR` + first-`EXPIRE` Lua script. Exceeding the window returns 429 with `Retry-After`; a Redis outage returns 503. Defaults: 30 chats/hour, 50 uploads/hour.
- **Login (fail open).** A Redis counter per client IP and per email (email hashed in the key) counts the attempt *before* authentication and is cleared only on success; exceeding 5 attempts / 5 minutes returns 429 with `Retry-After`. Redis errors log a warning and allow the attempt.

**Why:** an outage must not lock every user out of login, but it must not let chat and upload run unbounded either. `TRUST_PROXY_HEADERS` gates use of `X-Forwarded-For`; otherwise the socket peer address is used.

**Given up:** per-instance counters are not used — Redis is a hard dependency for limits — and login throttling can be bypassed during a prolonged Redis outage.

**Revisit:** add a small in-process fallback only if the fail-open window becomes an abuse problem; keep the fail-closed behavior for metered endpoints.

## Security headers and input validation

**Choice:** `SecurityHeadersMiddleware` sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, a no-referrer policy, a restrictive CSP, cross-origin policies and HSTS only on HTTPS. CORS is opt-in through `CORS_ORIGINS`/`CORS_ALLOW_CREDENTIALS` and is off by default. Validation is Pydantic/FastAPI-first: the custom 422 handler drops the submitted `input` and stringifies `ctx` values so passwords and exception objects are never echoed back.

**Why:** browser-facing hardening is centralized in middleware instead of duplicated per route, and validation errors cannot leak secrets into logs or clients.

**Given up:** the CSP is deliberately strict but static; any future third-party script or inline widget in the web app will need a policy change. HSTS is a no-op under the checked-in HTTP-only Caddy configuration.

**Revisit:** loosen individual CSP directives only with a concrete need, and re-audit headers when HTTPS is enabled.

## Audit log and multi-tenant isolation

**Choice:** `AuditLog` is append-only — there are no update or delete endpoints. Rows store `actor_email` plus nullable `user_id` and `workspace_id` foreign keys with `ondelete="SET NULL"`, so deleting an account or workspace preserves a redacted trail. Uploads, deletes, reindexing, workspace deletion, role changes and removals, provider key add/rotate/remove, export and account deletion are recorded; `GET /workspaces/{id}/audit-log` is owner/admin only.

**Isolation:** `WorkspaceContext` (user + workspace + caller role) is resolved once by `get_workspace_context`; `require_role` factories provide `MemberContext`, `OwnerContext` and `InviterContext`. Tenant-scoped repositories take `workspace_id` on every method and validate target objects through `ensure_workspace_scope`. A dedicated test enumerates all 29 workspace-scoped routes and asserts that non-members get 403 and foreign resource ids do not resolve.

**Why:** membership and role checks happen at the boundary, and every query carries the tenant filter, so a forgotten check in a service fails closed at the repository.

**Given up:** a little repetition (every repository method takes `workspace_id`), and audit history is intentionally not a full event log of reads.

**Revisit:** if the repository surface grows substantially, consider a scoped session factory that injects the tenant automatically — but keep the explicit filter in the PG integration tests.

**Account lifecycle:** `DELETE /account` removes storage objects and all owned user data while keeping the redacted audit trail; `GET /workspaces/{id}/export` returns workspace metadata as an attachment but excludes file bytes in v1. This makes account deletion deliberately non-erasing for audit history, a tradeoff to revisit if data-erasure requests become a requirement.

## Background worker, object storage and cleanup

**Choice:** ARQ rather than Celery — the codebase is fully async and Redis is already present, so no second broker/process model is needed. Uploads validate magic bytes and streamed size, write the object to MinIO under `<workspace_id>/<uuid>`, insert a `pending` row and enqueue `ingest_document`. A queue outage is logged and leaves the row `pending`. The worker downloads, extracts (PyMuPDF for PDFs with real page numbers, python-docx for DOCX, UTF-8 for TXT/MD), cleans running headers/footers and hyphenation, chunks, embeds in batches, and upserts chunks in one transaction with `chunks_done`/`chunks_total` progress. Retries use exponential backoff with a hard job timeout; empty/scanned and encrypted PDFs are permanent failures that do not consume retries.

**Why:** a failed ingest rolls back the whole chunk insert, so no half-ingested document ever becomes `ready`, and reprocessing is idempotent.

**Given up / tradeoff:** cleanup is best-effort. Deletes remove the MinIO object *before* the row so a storage failure cannot orphan a row, but a database failure after the object deletion can leave an object with no row. A periodic sweep to re-enqueue stale `pending` documents and remove orphan objects was identified but is not implemented.

**Revisit:** add a reconciliation sweep before long-term production use, or move to a transactional outbox if orphan objects become material.

## Next.js typed client from OpenAPI

**Choice:** `apps/api/export_openapi.py` dumps FastAPI's schema to `apps/web/lib/api/openapi.json`; `pnpm --filter web api:types` regenerates `lib/api/schema.d.ts` with `openapi-typescript`, and `lib/api/client.ts` wraps typed operations. The generator is pinned to TypeScript 5.9 via a pnpm override while the app uses TS 7.

**Why:** API changes surface as type errors in the web app instead of runtime surprises. The fetch wrapper detects already-prefixed `/api/v1` paths (a bug found in visual QA), sends `credentials: "include"` and retries after a silent refresh.

**Given up:** a regeneration step after every API change, and one toolchain override.

**Revisit:** generate types in CI and fail the build when `schema.d.ts` is stale.

## Production topology

**Choice:** multi-stage, non-root images for both apps (uv-frozen Python image, Next.js standalone server). `docker-compose.prod.yml` publishes only Caddy on port 80. The checked-in `Caddyfile` answers `/health` locally, proxies `/api/*` to `api:8000` (SSE upgrade headers pass through) and sends every other path — including invitation links — to `web:3000`. Postgres, Redis, the S3-compatible object store (exposed through the MinIO SDK settings), Ollama, the API and the worker stay on the Compose network with no host-published ports. `auto_https` is off: TLS is expected to be terminated upstream.

**Why:** one public port, one place to apply transport policy, and no risk of accidentally exposing a datastore with development credentials. The dev stack opts into reload through `docker-compose.override.yml`, which production does not load.

**Given up:** horizontal scaling is not transparent — ARQ queueing scales, but stream cancellation state does not (see above), and a single Caddy is a single point of entry. As checked in, Caddy has `auto_https off` and the production compose defaults `REFRESH_COOKIE_SECURE=false`, so the out-of-the-box topology is HTTP on localhost behind a trusted terminator, not a TLS-terminating edge.

**Revisit:** add a TLS-enabled domain matcher to the Caddyfile and set `REFRESH_COOKIE_SECURE=true` when deploying beyond a trusted network, and move stream state to Redis before adding API replicas.

## Startup, health and failure behavior

**Choice:** startup is staged by Compose dependencies: Postgres/Redis/object-store healthchecks gate a one-shot `migrate` service, and the API and worker wait for migrations to complete successfully. The API's lifespan creates the ARQ pool but tolerates a Redis outage at startup (uploads still work; ingestion waits), and closes the queue, embedder, Redis client and database engine on shutdown. `/health` is a liveness probe independent of dependencies; `/health/db` is a readiness probe that returns 503 when the database check fails. Caddy answers `/health` itself and healthchecks both upstreams before it starts.

**Why:** a bad migration must not leave a partially-running API accepting writes, while a transient Redis failure should not make the whole service unstartable.

**Given up:** readiness does not check the object store, Ollama or Redis, so a healthy `/health/db` is not a guarantee that ingestion or chat will succeed. A migration run leaves no rollback service — recovery is a database restore (see [backup.md](backup.md)).

**Revisit:** add dependency-aware readiness checks and an explicit rollback path before automated deploys.

## Evaluation harness

**Choice:** `evals/evaluate.py` sweeps chunk size, embedder, retrieval mode and reranking over 5 handbook documents, 42 questions (36 answerable, 6 unanswerable), using the *real* chunker, retrieval repository, RRF fusion, rerank hook, prompt builder, `ChatService.answer` and citation parser. Embeddings, reranking and answer generation are deterministic local stand-ins (hashing/TF-IDF vectors and extractive answers), documented in `evals/README.md`.

**Why:** runs are fast, reproducible and useful for *relative* comparisons. The resulting recommendation is 256-token chunks, the strongest available embedding, hybrid search, reranking on, and 20/5 candidate/final k.

**Given up:** absolute quality numbers are not production scores; SQLite keyword matching is substring-based, so hybrid and vector-only tie there while Postgres stemming may change the result.

**Revisit:** re-run against Postgres with the real embedding model, and replace the extractive LLM with the configured provider before quoting any quality number externally.

## Deferred items

| Item | Why deferred | Trigger to revisit |
|---|---|---|
| Mail-based password reset / email verification | No mail transport locally; out of scope | Any internet-facing deployment |
| Multi-worker stream coordination | Single-process `/stop` works locally | More than one API replica |
| Real cross-encoder reranker | Harness currently uses a deterministic stand-in | After the abstention fix, to measure true gain |
| Normalized citation table | JSON citations adequate for v1 volumes | Analytics of large histories or citation-accuracy regressions |
| Per-workspace embedding model selection | Global settings acceptable for v1 | Tenants needing different models |
| DNS-rebinding guard for BYOK URLs | Egress layer is the intended boundary | Untrusted multi-tenant hosting |
| Stale-job / orphan-object reconciliation sweep | Small local volumes | Long-running production deployment |
