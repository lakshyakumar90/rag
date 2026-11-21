# Decisions

## Embedding Model

- **Choice:** `embeddinggemma-2:440m` (served via Ollama)
- **Purpose:** Text embeddings for the RAG pipeline
- **Embedding dimension:** 768 (verified at runtime via `POST /api/embed` against `embeddinggemma-2:440m`; `ollama show` reports a 512-dim text encoder but the served embedding is 768-dim, so the runtime value is authoritative).
- **Date:** 2026-11-09

### Notes

- The embedding dimension must match the vector index/schema used by the retrieval store. If the model or dimension changes, re-embed existing content and update the index configuration accordingly.

## Open Decisions

### Key Scope

- **Status:** Open
- **Question:** Should API keys be scoped per user or per workspace?
- **Suggestion:** Per user.

### CLI Mode Scope

- **Status:** Open
- **Question:** What scope should CLI mode have?
- **Suggestion:** Local only, off by default, enabled with an environment flag.

## Authentication & User Endpoints (2.2)

Implemented under `/api/v1`: `POST /auth/register`, `/auth/login`, `/auth/refresh`,
`/auth/logout`, `/auth/change-password`, `GET /users/me`, `PATCH /users/me`.

- **Layering:** `schemas/` (request/response DTOs), `repositories/` (SQLAlchemy
  data access), `services/` (business logic), `api/v1/endpoints/` (thin HTTP
  layer). Services raise typed `DomainError` subclasses; one handler in
  `core/exceptions.py` maps them to the existing JSON error envelope, keeping
  services framework-agnostic.
- **Password policy:** 8–128 chars, at least one lowercase, uppercase, digit,
  and special character, plus a small denylist of very common passwords.
  Enforced by a reusable `StrongPassword` annotated type on registration and
  change-password only — not on login, so a password that predates a policy
  change remains usable. Argon2id hashing and rehash-on-login use the existing
  `core/security.py` helpers.
- **Email:** normalized to lowercase/trimmed and checked with a pragmatic
  regex (avoids adding `email-validator`). Uniqueness is enforced by the
  existing functional unique index, a pre-check, and `IntegrityError` handling
  for concurrent registrations. No verification flow yet; email is therefore
  not editable through `PATCH /users/me` (only `full_name` is).
- **Refresh tokens:** only a SHA-256 hash is stored (`refresh_tokens` table).
  JWTs carry a `type` claim so an access token cannot be used to refresh and
  vice versa. Rotation revokes the old row and inserts its replacement in one
  transaction, under `FOR UPDATE` to serialize concurrent refreshes. Reuse of
  an already-rotated token revokes the user's entire token family (theft
  mitigation).
- **Logout:** takes the refresh token in the body, needs no access token, and
  is idempotent (204 even for unknown/already-revoked tokens).
- **Change password:** requires a valid access token and the current password,
  rejects reusing the same password, revokes all refresh tokens (forces
  re-login everywhere), and issues no new tokens.
- **Registration response:** 201 with the created user only; clients call
  `/auth/login` to obtain tokens. 204 is used for the two no-content commands.
- **Validation errors:** the 422 details now omit the submitted `input` (so
  passwords are never echoed back) and stringify `ctx` values — Pydantic can
  put exception objects there, which previously crashed the error handler.
- **Login hardening:** password verification is also run against a dummy hash
  for unknown emails so "unknown email" and "wrong password" cost the same
  time.
- **No new config or migration needed:** JWT settings, ORM models, and the
  `users`/`refresh_tokens` migration were already present in the repo.

## Dependencies & Hardening (2.3)

- **`get_current_user`:** exported from `api/v1/dependencies.py` along with a
  `CurrentUser` alias used by protected routes. It validates the Bearer access
  token, enforces the `access` token type, and rejects unknown/inactive users
  with a structured 401.
- **Login rate limiting:** a Redis counter per client IP **and** per email
  (email hashed in the key to avoid storing PII). `INCR` + first `EXPIRE` +
  `TTL` for both keys run in one Lua script. The attempt is counted before
  authentication; only a successful login clears the counters. Exceeding the
  limit returns 429 with `Retry-After` (default: 5 attempts / 5 minutes).
  `TRUST_PROXY_HEADERS` must be enabled for `X-Forwarded-For` to be used; we
  otherwise trust `request.client.host`. Redis errors fail **open** with a
  warning — a cache outage should not lock everyone out of login.
- **Refresh-token delivery:** the refresh token is set only as an HttpOnly,
  Secure, SameSite cookie scoped to `/api/v1/auth`, and is never returned in a
  response body (`TokenResponse` intentionally has no refresh field). The body
  fallback on `/refresh` and `/logout` is retained for non-browser clients.
  `REFRESH_COOKIE_SECURE=false` exists for local plain-HTTP development only;
  SameSite=lax limits CSRF exposure. Changing the password also clears the
  cookie.
- **Client storage:** `apps/web/lib/auth-client.ts` keeps the access token in
  module memory (never localStorage), always sends `credentials: "include"`
  so the browser carries the HttpOnly cookie, and retries once after a silent
  refresh on a 401.
- **Tests:** pytest + pytest-asyncio + httpx ASGITransport, backed by a real
  in-memory SQLite database and a fake Redis (`apps/api/tests/`). Coverage:
  register (including weak password), login/cookie flags, wrong password,
  missing/malformed/expired/wrong-type tokens on protected routes, expired
  refresh token, rotation + reuse detection, logout, and rate limiting.
- **Dependencies:** added `redis` at runtime; `pytest`, `pytest-asyncio`, and
  `aiosqlite` as dev dependencies, with config in `pyproject.toml`. No schema
  migration was needed.

## Models (3.1)

Added `Workspace`, `Membership`, `Invitation` plus `MembershipRole` /
`InvitationStatus` enums and migration `f0fe71d60abb` (on top of
`2e7fd8e217f3`).

- **Workspace:** `name` and `slug` are normalized/validated on every ORM write;
  slug is unique, lowercase-checked in the DB, and constrained to
  `a-z0-9` with single hyphens at the app layer (a regex CHECK would not be
  portable to the SQLite test database). `created_by` references `users.id`
  with `ON DELETE RESTRICT` — a creator cannot disappear while their workspaces
  exist — and the relationship uses `passive_deletes` so the database decides.
- **Membership:** unique per `(user_id, workspace_id)`; both FKs use
  `ON DELETE CASCADE`. `role` is stored as `VARCHAR(20)` with a named CHECK
  rather than a native PG enum, so migrations stay simple; a small
  `StrEnumType` decorator still yields typed enum values on reads.
- **Invitation:** only the SHA-256 token hash is stored (unique, 64 hex chars),
  mirroring refresh tokens. Email is normalized like user email; `role`
  reuses `MembershipRole` (owner is allowed but normal invites use
  admin/member); `status` is pending/accepted/revoked/expired with a DB default
  of `pending`. `expires_at` is indexed for expiry sweeps. The workspace FK
  cascades on delete.
- **Indexes:** explicit indexes on all FKs plus invitation `email` and
  `expires_at`; token uniqueness comes from named unique constraints.
- **Tests** (`apps/api/tests/test_models.py`): slug/email normalization, slug
  and membership-pair uniqueness, enum round-trips, CHECK enforcement, default
  status, token-hash uniqueness, and workspace delete cascades.

## Endpoints (3.2)

All routes are under `/api/v1` and require a Bearer access token:

| Route | Who | Purpose |
|---|---|---|
| `POST /workspaces` | any user | creates the workspace; creator becomes its **owner** |
| `GET /workspaces` | member | lists the caller's workspaces |
| `GET /workspaces/{id}` | member | get one (response includes `my_role`) |
| `PATCH /workspaces/{id}` | **owner** | update name/slug |
| `DELETE /workspaces/{id}` | **owner** | delete (cascades members/invitations) |
| `POST /workspaces/{id}/invitations` | owner or admin | invite by email |
| `GET /workspaces/{id}/invitations` | member | list invitations (no tokens) |
| `GET /workspaces/{id}/members` | member | list members |
| `PATCH /workspaces/{id}/members/{uid}` | **owner** | change a member's role |
| `DELETE /workspaces/{id}/members/{uid}` | **owner** | remove a member |
| `POST /invitations/accept` | invited user | accept using the raw token |

- **Invitations without email:** the invite response returns the raw token and
  an `accept_url` (`INVITATION_ACCEPT_BASE_URL?token=...`) so the UI can display
  a link; only the SHA-256 token hash is stored. `INVITATION_TTL_DAYS` (7)
  controls expiry. Re-inviting the same email revokes older pending invites.
  Accepting checks status, expiry, and that the token's email matches the
  authenticated user; accepted invites cannot be reused, and an expired one is
  marked `expired` when encountered.
- **Last owner:** role changes/removals lock the workspace row (`FOR UPDATE`)
  and count owners before acting; demoting or removing the sole owner returns
  409 `LAST_OWNER`. Promoting a second owner first makes those operations legal.
- **Owner/admininvite:** owners and admins may invite; plain members get 403.
  Member management (role change/removal) and workspace update/delete are
  owner-only. These choices are stricter where the spec was silent.
- **Errors:** 404 unknown workspace/invitation, 403 non-member/owner-only,
  409 duplicate slug, already-member, reused invitation, or last-owner,
  410 expired invitation — all through the existing `DomainError` envelope.
- **Pydantic 2.14 note:** `model_validate(update=...)` no longer exists, so
  responses with request-specific fields (`my_role`, invite token/link) are
  constructed explicitly. `updated_at` uses `onupdate=func.now()` and is
  expired by the flush, so the update method refreshes the row through the
  async session before serializing (otherwise a sync lazy-load raises
  `MissingGreenlet`).
- **Tests** (`apps/api/tests/test_workspaces.py`): creation/ownership, slug
  uniqueness, member vs non-member access, owner-only update/delete, invite
  token+link, acceptance (wrong email / reused / expired), member listing,
  role changes, removal, and last-owner protection — 10 new end-to-end tests.

## Access Control (3.3)

- **`WorkspaceContext`** (in `services/workspaces.py`): `user` + `workspace`
  (from the path) + the caller's `role`. `get_workspace_context` in
  `api/v1/dependencies.py` resolves it once: unknown workspace → 404, known
  workspace where the caller has no membership → 403. All protected workspace
  endpoints now declare a context dependency instead of re-checking
  membership in the service.
- **`require_role(*roles, error=...)`**: dependency factory for role checks.
  Module-level aliases keep FastAPI's dependency cache stable:
  `MemberContext` (any member), `OwnerContext` (owner only, keeps the
  `OWNER_REQUIRED` code), and `InviterContext` (owner or admin). Generic role
  failures return `INSUFFICIENT_ROLE` with `required_roles`/`current_role`
  details — so a member trying to invite now gets `INSUFFICIENT_ROLE`, while
  owner-only actions keep `OWNER_REQUIRED`.
- **Tenant-scoped repositories:** every method of `WorkspaceRepository`,
  `MembershipRepository` and `InvitationRepository` now takes `workspace_id`
  and uses it in the SQL filter (`get_by_slug` uses it to exclude the row
  being updated; `list_for_user` can narrow to one workspace). Write methods
  take `workspace_id` too and validate the object's tenant through
  `repositories.base.ensure_workspace_scope` — a mismatch raises `ValueError`
  (a bug, not a user error). The only global lookups left are deliberately
  cross-tenant: user/refresh-token tables (identity, not workspace data),
  global slug uniqueness checks, and invitation redemption by token (the
  caller is not a member yet, so email/expiry checks gate that path).
- **Tests** (`apps/api/tests/test_access_control.py`): two users in two
  workspaces; A cannot list, get, update, delete, invite into, list
  invitations/members of, change roles in, or remove members from B, and
  cannot redeem B's invitation; B's data is verified unchanged afterwards.
  Also covers cross-workspace target ids (404 `MEMBER_NOT_FOUND`), member vs
  owner vs admin role checks, and unknown workspace (404). 5 new tests;
  35 total pass.

## File Upload & Storage (Phase 4)

- **Models:** `Document` (`workspace_id`, `uploaded_by`, filename, mime_type,
  size, sha256, storage_key, status, error, page_count) and a minimal
  `DocumentChunk` table so "delete cascades to chunks" is real. Embeddings and
  real chunking belong to a later phase; `page_count` stays null for now.
  Migration `800b87a0f86f` adds both tables with `ON DELETE CASCADE` FKs and
  a `(workspace_id, sha256)` index.
- **Storage:** `providers/storage.py` defines a `StorageClient` protocol;
  `providers/minio.py` implements it with the MinIO SDK via `to_thread`, a
  lazily-ensured bucket, and a defensive check that keys start with
  `<workspace_id>/`. Tests inject an in-memory fake via
  `get_storage_client`. Added `minio` + `python-multipart` dependencies.
- **Validation:** allowed extensions PDF/DOCX/TXT/MD; the client-provided
  content type is ignored. Magic bytes decide the real type (`%PDF-`, ZIP +
  `word/document.xml` for DOCX, UTF-8/no NUL for text) and must match the
  extension → 415 `UNSUPPORTED_FILE_TYPE`. Size is enforced while streaming
  (default 25 MB) → 413 `FILE_TOO_LARGE` with `max_size_bytes`.
- **Filenames/keys:** sanitized to a safe basename (both separators handled,
  control chars removed); stored under `<workspace_id>/<uuid>` with no
  client-controlled path. Duplicate sha256 within a workspace → 409
  `DUPLICATE_DOCUMENT` with the existing id; failed uploads are excluded so a
  retry is possible.
- **Lifecycle:** upload writes a `pending` row, then stores bytes and marks it
  `ready`; storage failure marks the row `failed` and returns 503. Delete
  removes the object first (so a storage failure never orphans the row),
  then the row and its chunks. A presigned-URL endpoint is provided for reads.
- **Endpoints:** `POST/GET /workspaces/{id}/documents`, `GET/DELETE
  /documents/{doc_id}`, `GET /documents/{doc_id}/url`; pagination via
  `skip`/`limit` and `?status=` filter. Members may view; owners/admins may
  upload/delete (reusing `require_role`). All reads/writes are workspace_id
  filtered; cross-tenant access returns 403.
- **Tests** (`apps/api/tests/test_documents.py`): round-trip, storage key
  layout, pagination/status filter, oversize, wrong magic bytes/non-DOCX ZIP,
  all four allowed types, duplicate detection scoped per workspace, role
  rules, cross-tenant denial on every endpoint, chunk cascade, 404s. 10 new
  tests; 45 total pass.

## Background Worker (5.1)

- **Choice: ARQ, not Celery.** The codebase is fully async (async SQLAlchemy,
  async MinIO wrapper, async Redis), and Redis is already in compose. ARQ is
  async-native and needs no separate broker/result backend; Celery would add a
  second process model and sync task conventions. ARQ 0.28 requires `redis<6`,
  so the existing dependency was pinned to `>=5,<6`.
- **Queue abstraction:** `providers/queue.py` defines a `JobQueue` protocol and
  an `ArqJobQueue` using a shared `ArqRedis` pool created in app startup and
  closed on shutdown. Tests override `get_job_queue` with `FakeJobQueue`.
  Upload commits the document row first, then enqueues `ingest_document`;
  a queue outage is logged and leaves the row `pending` rather than failing a
  successfully stored file (a later recovery sweep can re-enqueue).
- **Status flow changes:** uploads now stay `pending` (previously marked
  `ready` immediately); the worker moves them `processing` → `ready`.
- **Worker container:** compose `worker` service shares the API image and runs
  `arq workers.settings.WorkerSettings`, waiting for Redis/Postgres/migrations.
  Shared env now also sets `REDIS_HOST`/`MINIO_HOST` for container networking.
- **Retries/backoff/timeout/failure:** the task uses ARQ's `ctx["job_try"]` and
  raises `Retry(defer=base * 2**(try-1))` with `INGEST_MAX_TRIES` (3) attempts;
  an internal `asyncio.wait_for` enforces `INGEST_JOB_TIMEOUT_SECONDS` (so
  timeouts are ordinary exceptions that participate in the same retry logic).
  Only on the final attempt does the task persist `status=failed` and the
  error text on the document row, then re-raise so ARQ marks the job failed.
  The session factory is injected through `WorkerSettings.ctx`, making the
  task testable against SQLite.
- **Ingestion is a placeholder** (`workers/ingest.py`): it records state
  transitions; real chunking/embedding lands in the RAG phase.
- **Tests** (`apps/api/tests/test_worker.py`): upload enqueues the right
  document id, queue outage does not fail upload, success → ready, retry
  backoff values, no failure recorded before the last try, terminal failure
  persisted, timeout persisted, worker settings. 7 new tests; 52 total pass.

## Extraction (5.2)

- **Libraries:** PyMuPDF for PDF (`page.get_text`, real page numbers) and
  python-docx for DOCX (paragraphs + table cells); TXT/MD are UTF-8 reads.
  Extraction runs in `asyncio.to_thread` from the ARQ task.
- **Cleaning** (`workers/extraction.py`): collapse repeated whitespace,
  repair `inter-\nnational` hyphenation, and strip running headers/footers —
  lines appearing on ≥60% of pages (min 4 chars) plus numeric-only page labels.
  Only applied across multi-page documents (≥3 pages).
- **Chunking:** cleaned pages are split into ≤1000-character word-boundary
  chunks. Added a nullable `page_number` column to `document_chunks`
  (migration `e27794609ef5`) so PDF provenance survives; it is null for
  TXT/MD/DOCX. The worker deletes old chunks before writing new ones, making
  reprocessing idempotent, and stores the real PDF `page_count` on the document.
- **Empty/scanned PDFs:** no selectable text (under 20 chars across all pages,
  including graphics-only pages) raises `EmptyDocumentError` with a message
  that explicitly says OCR is unavailable; encrypted PDFs raise
  `EncryptedDocumentError`. These are **permanent** extraction errors: the
  worker records `status=failed` + the message on the document immediately,
  without consuming retry attempts. Transient errors (e.g. storage) keep the
  previous retry-with-backoff behavior.
- **Worker context** now injects a `StorageClient` as well as the session
  factory; tests supply an in-memory fake and can exercise the full
  download → extract → chunk → persist path.
- **Tests:** PDF page numbers + header/hyphenation cleaning, DOCX/TXT/MD,
  empty and graphics-only PDF rejection, chunk page numbers, worker storing
  chunks, permanent failure without retry. 5 new tests; 57 total pass.

## Chunking (5.3)

Three strategies in `workers/chunking.py`, all returning the same `Chunk`
(page number, index, text, heading path, token count):

- **V1 `fixed`:** token-sized windows over whitespace units (~500 tokens,
  50-token overlap) using exact source slices so original text is preserved.
- **V2 `paragraph`:** paragraph- and sentence-aware packing. Short paragraphs
  stay intact; long ones are split at sentence boundaries; oversized sentences
  fall back to V1 windows. Overlap carries a token-sized tail, but is dropped
  when it would push the next chunk over the target.
- **V3 `heading`:** same packer, but each section carries a heading path.
  Markdown ATX headings (`#`/`##`/…) and DOCX `Heading N` styles build a
  heading stack; paths are stored as JSON on the chunk. `auto` (default)
  selects `heading` when a document has heading paths, otherwise `paragraph`.

- **Tokenizer:** a deterministic offline regex tokenizer (words/numbers/
  punctuation count as one, each CJK/emoji code point as one). No model-specific
  vocabulary or network download; counts are stable and approximate until an
  embedding stack is chosen.
- **Schema:** `document_chunks` gains `heading_path` (JSON list, nullable) and
  `token_count` (integer, default 0, non-negative CHECK) in migration
  `48342d253c7e`. Chunks still carry document/workspace ids, index, text and
  page. The worker persists all of these and remains idempotent on reprocessing.
- **Tests** (`apps/api/tests/test_chunking.py`, plus worker integration):
  overlap/target sizes, page numbers, paragraph and sentence boundaries,
  oversized single tokens, tiny files, CJK/unicode, Markdown and DOCX heading
  paths, invalid settings, and DB persistence of all chunk fields. 13 new unit
  tests + 1 integration test; 70 total pass.

## Embeddings (5.4)

- **Choice: Ollama**, since `embeddinggemma-2:440m` is already installed and the
  service is in compose. `providers/embeddings.py` defines an `EmbeddingProvider`
  protocol (`embed_documents`, `embed_query`, `dimension`) and
  `OllamaEmbeddingProvider` using `POST /api/embed`. fastembed was not chosen to
  avoid shipping a second model/runtime alongside Ollama.
- **Batching/retries/timeouts:** inputs are split into batches of
  `EMBEDDING_BATCH_SIZE` (32); each request has `EMBEDDING_TIMEOUT_SECONDS` (60)
  and up to `EMBEDDING_MAX_RETRIES` (3) attempts with exponential backoff for
  timeouts, connection errors, 429 and 5xx. Other 4xx and malformed responses
  are permanent and fail immediately. Response count and
  `EMBEDDING_DIM` (768, verified earlier at runtime) are validated.
- **Normalization:** L2-normalized by default (`EMBEDDING_NORMALIZE=true`) so
  cosine similarity is correct; can be disabled for models that already return
  unit vectors.
- **Config scope:** global settings for v1 (explicitly allowed by the spec);
  per-workspace `embedding_model`/`embedding_dim` selection is deferred.
- **Persistence:** vectors are stored as JSON on `document_chunks.embedding`,
  with `documents.embedding_model`/`embedding_dim` for provenance (migration
  `5518ae5a1925`). A pgvector column/index belongs to the retrieval phase.
  The worker injects the provider through `WorkerSettings.ctx` and fails/retries
  the job if embedding fails, so no document is marked ready without vectors.
- **Tests** (`apps/api/tests/test_embeddings.py`): batching, query path, empty
  input, normalization, dimension/count validation, permanent 4xx, retry on
  5xx and timeout. Worker tests verify vectors are persisted. 9 new tests;
  79 total pass. (Live Ollama is running here, but the installed model cannot
  start because the `llama-server` binary is missing, so HTTP is mocked in tests.)

## Storage & Indexes (5.5)

- **Vector column:** `document_chunks.embedding` is now a `vector(768)`
  (matching `EMBEDDING_DIM`) via a `VectorType` TypeDecorator that emits
  pgvector on Postgres and JSON on SQLite, so tests still run without a PG
  server. Migration `65223e6f8aab` converts existing JSON vectors with
  `embedding::text::vector(768)`.
- **Indexes:** partial HNSW index with `vector_cosine_ops` on non-null vectors,
  and a GIN index on a generated `search_vector tsvector` column
  (`to_tsvector('english', content)`). Both created with `IF NOT EXISTS`.
  `TSVectorType` maps to TSVECTOR on PG and Text on SQLite (where tests write a
  simple lowercase token string instead).
- **Batched writes + progress:** `documents` gains `chunks_total`/`chunks_done`.
  The worker deletes old chunks, sets the totals, inserts in batches of
  `CHUNK_INSERT_BATCH_SIZE` (100) with `flush()` after each batch — all in one
  transaction — advances `chunks_done`, then sets status `ready` and commits.
  A failure rolls the whole thing back, so no half-ingested document is ready.
- **Re-index:** `POST /workspaces/{id}/documents/{doc_id}/reindex` (owner/admin)
  deletes chunks, clears the error/progress, sets status `pending`, and
  enqueues a fresh `ingest_document` job. The chunk delete is filtered by both
  document and workspace id, preserving tenant isolation.
- **Tests** (`apps/api/tests/test_storage.py`): batched inserts and progress,
  vector/tsvector columns on SQLite, re-index reset/enqueue, re-index role and
  cross-tenant rules, and an offline Alembic SQL check for `vector(768)`,
  HNSW/cosine and GIN/tsvector. 5 new tests; 84 total pass.

## LLM Interface (6.1)

- **Protocol** (`providers/llm/base.py`): `LLMProvider` with
  `stream(messages, **opts) -> AsyncIterator[LLMEvent]` and
  `complete(messages, **opts) -> Completion`; runtime-checkable so adapters can
  be verified structurally. Options are keyword args, with common names
  (`model`, `temperature`, `max_tokens`) mapped by each adapter.
- **Normalized types** (`providers/llm/types.py`): `ChatMessage(role, content)`
  and stream events `TextDelta`, `Usage`, `Finish`, `Error` (union `LLMEvent`).
  `complete` returns `Completion(text, finish_reason, usage)`. Unknown provider
  finish reasons map to `other` instead of raising.
- **Registry/factory** (`providers/llm/registry.py`): name → factory map with
  `register_provider`, `available_providers`, and `create_llm_provider` which
  defaults to `LLM_PROVIDER` (`ollama`). Unknown names raise
  `UnknownProviderError`.
- **Built-in adapter:** `OllamaLLMProvider` uses Ollama's NDJSON `/api/chat`,
  emitting text deltas, then usage, then finish; HTTP/JSON failures emit an
  `Error` event rather than killing the stream, and `complete` aggregates the
  same stream into one result so both paths behave identically.
- **Tests** (`apps/api/tests/test_llm.py`): protocol conformance, normalized
  event ordering/aggregation, error events, option mapping, registry built-ins
  and custom providers. 8 new tests; 92 total pass. HTTP is mocked; no live
  model call is needed for the interface.

## Adapters (6.2)

- **OpenAI-compatible adapter** (`providers/llm/openai_compat.py`): configurable
  `OPENAI_BASE_URL`/`OPENAI_API_KEY`/`OPENAI_MODEL` via `POST
  /chat/completions`, so the same adapter covers OpenAI, Gemini's compatible
  endpoint, Ollama's `/v1`, OpenRouter and Groq. SSE is parsed by hand
  (`providers/llm/sse.py` handles comments, multi-line `data:` and `[DONE]`);
  text deltas, usage and finish are normalized, with finish emitted last.
- **Anthropic adapter** (`providers/llm/anthropic.py`): `POST /v1/messages` with
  `x-api-key` and `anthropic-version`; system messages are folded into the
  top-level `system` field. Its own event types (`message_start`,
  `content_block_delta`, `message_delta`, `message_stop`) map to the same
  normalized deltas/usage/finish (`end_turn`→stop, `max_tokens`→length).
- **Errors:** provider HTTP/API failures map to `AuthenticationError`,
  `RateLimitError` (preserving `Retry-After`), `ContextLengthError` and
  `ProviderAPIError` (`providers/llm/errors.py`), instead of leaking httpx or
  provider-specific exceptions. Transport failures still emit `Error` events.
- **Registry:** adds `openai`, `openai-compatible` and `anthropic` factories,
  all selectable through `LLM_PROVIDER`.
- **Tests** (`apps/api/tests/test_llm_adapters.py`): SSE parsing, error mapping,
  both adapters' event ordering/payloads/headers, system extraction, HTTP
  error mapping, and factory construction. 8 new tests; 100 total pass. All HTTP
  is mocked; no API keys or live endpoints are required.

## BYOK Key Management (6.3)

- **Model** (`ProviderConfig`): `user_id`, `provider_type`, `base_url`, `model`,
  `encrypted_api_key`, `key_last4` (migration `ed3feb203165`). All repository
  reads/writes are filtered by `user_id`; there is no endpoint that can reach
  another user's config.
- **Encryption:** Fernet with `LLM_MASTER_KEY` from the environment
  (`core/crypto.py`). The plaintext key is never logged, returned, or stored;
  only the ciphertext and last four characters. `ProviderConfigResponse` has no
  key fields at all, and connection-test errors are sanitized by replacing the
  plaintext secret with `***`. A missing/invalid master key returns 503.
- **SSRF guard:** `core/net.py` requires http(s) with a host and no embedded
  credentials, and blocks localhost, loopback/private/link-local/reserved IPs
  unless `LOCAL_MODE_ENABLED=true`. DNS names are allowed; DNS-rebinding
  protection belongs in the production egress layer (documented limitation).
- **Endpoints:** `POST/GET /provider-configs`, `GET/PATCH/DELETE
  /provider-configs/{id}`, and `POST /{id}/test`. Update rotates the key by
  supplying a new `api_key`. Test connection decrypts in memory, builds the
  provider via the registry, sends a one-token request, reports
  `ok`/`message`/`latency_ms`, and maps failures to `ConnectionTestError` (502).
- **Tests** (`apps/api/tests/test_provider_configs.py`): crypto round-trip,
  master-key requirement, URL blocking/local-mode, CRUD with no key leakage
  (also checked via caplog), cross-user 404s, successful and sanitized-failure
  connection tests. 8 new tests; 108 total pass.

## CLI Provider (6.4)

**Docs studied (current, 2026-11-21):**
- Codex: `codex exec --json` emits JSONL (`item.completed` with
  `item.type=agent_message`, `turn.completed` with usage). Read-only sandbox is
  the default; `--full-auto` is deprecated in favour of explicit sandbox flags.
  Also `--ephemeral`, `--skip-git-repo-check` (temp cwd is not a git repo) and
  `--ignore-user-config` to avoid user config/MCP servers.
- OpenCode: `opencode run --format json` emits JSONL (`text`, `step_finish`,
  `finish`, `error`). `--auto` auto-approves permissions, so it is never used;
  `--standalone` avoids the shared background service.
- Claude Code: `claude -p --output-format stream-json` emits `assistant`,
  `result` and `error` events. `--tools ""`, `--disallowedTools "*"`,
  `--permission-prompts none` and `--strict-mcp-config` remove tools and deny
  prompts; `--dangerously-skip-permissions` is never used.

- **Safety:** `asyncio.create_subprocess_exec` (never a shell), a fresh temp cwd
  per call (removed in `finally`), no auto-approve or writable-sandbox flags,
  a shared concurrency semaphore, hard timeout with process termination, and
  structured JSONL parsing only — stderr and scraped text are never used.
- **Docker decision:** CLI providers require the host's binaries and login, so
  the backend must run on the host. The API refuses to construct a CLI provider
  inside a container; a host bridge via `host.docker.internal` is the future
  option and is explicitly not implemented. README includes the warning.
- **Status endpoint:** `GET /api/v1/providers/cli/status` reports enabled,
  container state and per-tool installed/logged-in flags (read-only probes;
  raw probe output is never returned).
- **Prompt injection:** document text is wrapped in `<untrusted>` markers as
  data, and the real boundary is no tools + read-only + empty cwd. A test feeds
  a "run calc" payload and verifies no command event becomes a text delta and
  no dangerous flag is passed.
- **Tests** (`apps/api/tests/test_cli_providers.py`): disabled-by-default and
  container guard, argv safety for all three, structured parsers, identical
  streamed text from all three formats, timeout cleanup, injection resistance
  and status endpoint. 15 new tests; 123 total pass.

## Retrieval (7.1)

- **Vector search:** parameterised SQL with `1 - (embedding <=> :vector)` as
  cosine score, filtered by `workspace_id`, ready documents, non-null vectors
  and optional document ids, ordered by distance with a bound top-k. SQLite
  tests fall back to Python cosine over the JSON vectors.
- **Keyword search:** `websearch_to_tsquery('english', :query)` +
  `ts_rank_cd` against the generated `search_vector`, with the same workspace
  and document filters; SQLite falls back to token overlap. Non-positive
  scores are dropped so a zero vector never becomes a "match".
- **Fusion:** `reciprocal_rank_fusion` uses `1/(k + rank)` (k=60) and
  normalizes by the best achievable single-list rank-1 score, so the
  configured threshold is meaningful. Overlapping hits accumulate score.
- **Reranking:** optional `Reranker` calls a TEI-compatible `/rerank`
  endpoint; disabled by default and failures fall back to fused order.
- **Threshold:** best score below `RETRIEVAL_SCORE_THRESHOLD` (0.15) returns
  `answerable=False` and `answer="I don't know"`; metadata items are still
  returned so callers can inspect why.
- **Endpoint:** `POST /workspaces/{id}/search` (any member), with optional
  `top_k` and `document_ids`. Document filters and workspace scoping are both
  enforced in the repository, so cross-tenant ids simply return no rows.
- **Tests** (`apps/api/tests/test_retrieval.py`): RRF unit tests, PG SQL
  assertions, hybrid/keyword-only matches, document filters, cross-tenant
  denial, threshold fallback and reranker reordering. 7 new tests; 130 total
  pass. Live Postgres/Ollama are not available, so SQL is verified by source
  assertions and execution paths by SQLite plus a fake embedder.

## Prompting (7.2)

- **System prompt** (`core/prompting.py`): answer only from `<context>`, reply
  exactly "I don't know" when evidence is missing, cite every claim with `[n]`,
  and explicitly treat context text as untrusted data (never instructions).
- **Context builder**: numbers sources 1..N with document/page/heading
  metadata, wraps them in `<context>/<source>` delimiters, and fits a
  `PROMPT_CONTEXT_TOKEN_BUDGET` (2000) using the offline tokenizer. Text is
  sanitized (control chars removed, delimiter tags escaped) so a document
  cannot break out of its source block; truncation is flagged.
- **Citations**: `[n]` references in the answer are parsed and mapped back to
  chunk/document ids; unknown and duplicate numbers are ignored.
- **Chat flow**: `POST /workspaces/{id}/chat` retrieves, then skips the LLM
  entirely when retrieval is not answerable (returning "I don't know"), else
  prompts the chosen provider and returns the answer with citations and the
  numbered sources. Provider clients are closed after each call.
- **Injection defense:** layered — delimiters + explicit "untrusted data" rule
  + escaped tags + no tool access in adapters + read-only CLI sandboxes
  (from 6.4). Tests verify an injected "run calc" string stays inside the
  escaped context and cannot close it.
- **Tests** (`apps/api/tests/test_prompting.py`): system-prompt rules,
  numbering/delimiters, token budget, sanitization, citation mapping, LLM
  skip-on-no-evidence, and an end-to-end chat with citations. 9 new tests;
  139 total pass.

## Conversations (7.3)

- **Models** (migration `f5b27650e65e`): `Conversation(workspace_id, user_id,
  title)` and `Message(role, content, citations JSON, provider, model,
  input/output tokens, latency_ms)`. All reads are filtered by workspace and
  user; non-members get 403 from the workspace dependency, unknown ids 404.
- **Query rewriting:** for follow-ups with history, a small LLM call rewrites
  the question into a standalone one before retrieval; failures fall back to
  the original query. The original text is what gets stored and displayed.
- **History truncation:** newest messages that fit
  `CHAT_HISTORY_TOKEN_BUDGET` (1200) are injected between the system prompt and
  the current question; truncation never drops the newest message.
- **Auto titles:** first-message conversations with the default title get a
  short title from the LLM (max six words), with a query-prefix fallback.
- **Persistence:** the chat endpoint with `conversation_id` stores both the
  user message and the grounded assistant message (citations serialized with
  string ids so JSON columns stay portable), including usage and latency.
- **Endpoints:** conversation create/list/get/delete and message listing under
  `/workspaces/{id}/conversations`; `POST /chat` accepts an optional
  `conversation_id` and echoes it back.
- **Ordering:** messages have an explicit `sequence` per conversation
  (migration `a42ce9b566e4`) because `now()` is identical for all rows in one
  transaction; history and message listings order by sequence, not timestamp.
- **Tests** (`apps/api/tests/test_conversations.py`): CRUD/isolation, history
  truncation, persisted message metadata, auto title, and follow-up rewriting
  using prior turns. 4 new tests; 143 total pass.

## Chat Endpoint (7.4)

- **SSE:** `POST /workspaces/{id}/chat` now streams `data:` frames with event
  types `sources`, `token`, `done` and `error`. The previous JSON behavior is
  preserved at `POST /chat/complete` (same pipeline, non-streaming).
- **Persistence:** the streaming generator persists the user message and the
  assistant message in a `finally` block, so partial answers are saved on client
  disconnect or cancellation; a `done` frame is suppressed on disconnect.
- **Stop:** `POST /conversations/{id}/stop` cancels the active generation task
  via an in-process registry keyed by conversation id. This works for a single
  API process; multi-worker deployments would need shared state (documented
  limitation).
- **Regenerate:** `POST /conversations/{id}/regenerate` deletes the last
  user/assistant turn and generates a fresh answer, keeping the conversation
  length unchanged.
- **Conversation management:** PATCH rename added alongside the existing list
  and delete endpoints.
- **Usage tracking:** provider token usage is stored when available; otherwise
  tokens are estimated with the offline tokenizer and `tokens_estimated=true`
  is persisted on the message (migration `aa7a9853ef45`) and reported in `done`.
- **Tests** (`apps/api/tests/test_streaming_chat.py`): event sequence/citations,
  provider usage vs estimation, disconnect persistence, stop helper, regenerate
  and rename. 5 new tests; 148 total pass.

## Frontend Setup (8.1)

- **Stack:** Next.js App Router + TypeScript (already present), Tailwind CSS v4
  via `@tailwindcss/postcss`, and a local shadcn-style component set
  (`Button`, `Input`, `Card` built on CVA + `cn()`), plus TanStack Query,
  next-themes and lucide icons.
- **Typed API client:** `apps/api/export_openapi.py` dumps FastAPI's OpenAPI
  document to `apps/web/lib/api/openapi.json`; `pnpm --filter web api:types`
  regenerates `lib/api/schema.d.ts` with `openapi-typescript`. `lib/api/client.ts`
  exposes typed operations backed by the generated `components`/`paths` types.
  openapi-typescript needs the TS 5 factory API, so pnpm overrides its
  TypeScript to 5.9 while the app stays on TS 7.
- **Fetch wrapper:** the access token lives only in memory; `authFetch` adds
  it, sends the HttpOnly refresh cookie, and retries once after `/auth/refresh`
  on 401. `apiRequest` parses the app's `{ error }` envelope into `ApiError`.
- **Auth state:** `AuthProvider` mirrors the token store into React, loads the
  current user with TanStack Query, and exposes login/register/logout
  mutations. `AuthGuard` redirects unauthenticated users to `/login`; `/` routes
  to `/dashboard` or `/login`.
- **Theme:** next-themes with class-based dark mode and Tailwind CSS variables;
  `ThemeToggle` switches light/dark. Login/register/dashboard pages use the
  shared primitives.
- **Verification:** `pnpm check-types`, `pnpm lint` and `pnpm build` all pass
  (routes `/`, `/login`, `/register`, `/dashboard`).

## Frontend Pages (8.2)

- **Navigation:** workspace-scoped layout with a picker, links to
  documents/chat/members/settings, and a client `AuthGuard`.
- **Documents:** native drag-and-drop upload with XHR progress (fetch cannot
  report upload progress), status badges, delete, re-index retry, empty state,
  skeletons and error toasts.
- **Chat:** conversation sidebar (new/select/delete), SSE streaming via a
  `ReadableStream` reader, React Markdown + GFM rendering, stop (AbortController
  + `/stop`), regenerate, and citation chips that open a side panel with
  snippet, document name, page and heading path. Snippets come from a
  companion `/search` call because `SourceRef` carries ids, not text.
- **Members:** invite form producing a shareable accept link (new
  `/invitations/accept` page), pending invitations, role dropdown and removal.
- **Settings:** profile update, BYOK provider CRUD with key masking and test
  connection, and CLI status listing.
- **Feedback:** sonner toasts, skeleton loaders and empty states across pages.
- **Verification:** `pnpm check-types`, `pnpm lint` and `pnpm build` pass; build
  emits all workspace pages as dynamic routes.

## Frontend Streaming (8.3)

- **SSE reader:** `lib/chat-stream.ts` consumes the POST response with
  `response.body.getReader()`, normalizing CRLF, joining multi-line `data:`
  fields, retaining trailing partial frames between reads and flushing a final
  unterminated frame at EOF. Malformed JSON becomes an `error` event.
- **Reconnect:** a bounded retry (one attempt with linear backoff) runs only
  when the stream fails before any token was emitted; retrying after content
  would duplicate the assistant message. Aborts are never retried. The backend
  has no replayable event ids, so reconnects start a fresh generation.
- **Cancellation:** the chat page owns an `AbortController`, calls `/stop`, and
  suppresses abort errors; the stream helper checks `signal.aborted` between
  reads and before retrying.
- **Document status:** the documents query polls every 1.5s only while any
  document is `pending`/`processing`, and stops once all settle; progress bars
  use `chunks_done`/`chunks_total` from the generated `DocumentResponse`.
- **End-to-end path:** sign up → dashboard → create workspace → Settings → add
  BYOK provider → Documents → drag-drop upload → wait for `ready` → Chat →
  streamed answer with citation chips. All steps are wired through the typed
  client and shared auth/query providers.
- **Verification:** `pnpm check-types`, `pnpm lint` and `pnpm build` pass.

## UI Redesign (8.4)

- **Direction:** user-pinned minimal developer-console / editorial workspace:
  pure black in dark, warm off-white in light, one neutral family, one cobalt
  signal reserved for active state, primary action and focus. Captured in
  `apps/web/PRODUCT.md`, `DESIGN.md`, `.impeccable/design.json` and a surface
  brief; no concept roll because the direction was pinned in the brief.
- **Components:** expanded the local shadcn-style set with Radix Dialog,
  DropdownMenu, Select, Tabs, Tooltip, Separator and Slot, plus cmdk command
  palette (⌘K), lucide icons and sonner toasts.
- **Shell:** a 220px desktop rail (workspace switcher, four nav items, user
  menu) becomes a sticky top bar plus 64px bottom tabs below 768px; chat's
  conversation sidebar becomes a bottom sheet and citation panel an edge sheet.
- **Craft:** ruled full-width rows instead of card grids, status as neutral mono
  text (no colored pills), skeletons that keep the real row pitch, hydration-safe
  theme toggles, themed selection/caret/scrollbar, 44px coarse-pointer targets,
  and one authored entrance animation for streamed content.
- **Bug found during visual QA:** the typed client prefixed `/api/v1` twice;
  `authFetch`/upload now detect already-prefixed paths and use the origin only.
- **Review:** independent finish review found three medium issues (colored
  status pills, theme-switch hydration issues, 320px composer risk). All were
  fixed in one batch and scored resolved; final disposition **ship**. Detector
  clean. Captures live in `apps/web/.impeccable/review/` (desktop/mobile, both
  themes, plus 320px).

## Production Hardening (9)

- **Rate limits:** `UserRateLimiter` keeps one Redis counter per user and action
  (`ratelimit:user:{id}:{chat|upload}`), atomically incremented with an
  `INCR`/first-`EXPIRE` Lua script. Chat and upload endpoints call `check()`;
  exceeding the window returns 429 with `Retry-After`, and a Redis outage
  returns 503. This **fails closed** on purpose: login throttling keeps its
  fail-open behaviour (a cache outage must not lock everyone out), but chat
  and upload are metered and must not run unbounded during an outage.
- **Feedback:** `POST /workspaces/{id}/messages/{message_id}/feedback` stores a
  thumbs up/down plus an optional comment, unique per (message, user) so a
  second vote updates in place. Only assistant messages in the caller's workspace
  are accepted (404 otherwise); tenant membership is enforced by the workspace
  dependency.
- **Usage v1 is derived, not counted:** `GET /workspaces/{id}/usage` computes
  queries from user messages, tokens from assistant `input_tokens +
  output_tokens`, storage from `Document.size`, and includes feedback totals.
  `answerable` is now persisted on assistant messages by both the streaming and
  non-streaming chat paths so low-confidence answers can be reported.
- **Analytics:** `GET /workspaces/{id}/usage/analytics` (owner/admin) reports
  the ten most asked normalized questions, a low-confidence count together with
  the questions that produced those answers (paired by conversation and message
  sequence), and the ten most cited documents. Most-cited is computed in Python by reading the
  `Message.citations` JSON. This is adequate for v1 volumes but does not scale
  to arbitrary history; a normalized citation table is the natural next step.
- **Audit log:** `AuditLog` is append-only (no update/delete endpoints). Rows
  keep `actor_email` and use nullable `user_id`/`workspace_id` with
  `ondelete="SET NULL"` so deleting an account or workspace preserves history.
  Uploads, deletes, reindex, workspace deletion, member role changes/removals,
  provider key add/rotate/remove, workspace export and account deletion are
  recorded. `GET /workspaces/{id}/audit-log` is owner/admin only.
- **Security:** a `SecurityHeadersMiddleware` sets nosniff, DENY frame options,
  no-referrer, a restrictive CSP, cross-origin policies and HSTS on HTTPS.
  Input validation remains Pydantic/FastAPI-first; the validation error handler
  strips submitted values so secrets are not echoed back.
- **Account data:** `DELETE /account` removes storage objects, owned
  workspaces, documents, conversations, memberships, invitations, provider
  configs and refresh tokens, while keeping a redacted audit trail.
  `GET /workspaces/{id}/export` returns workspace metadata (documents,
  conversations, messages, members) as an attachment; file bytes are not
  included in v1.
- **Deferred:** password reset and email verification need a mail transport,
  which is not available locally, and are outside the "Done when" criteria.
- **Verification:** ruff, format and mypy clean; 160 backend tests pass,
  including 12 new tests for limits, feedback, usage/analytics, audit, export,
  deletion and security headers. `alembic upgrade head --sql` emits the new
  tables and indexes. `pnpm audit` reports 19 pre-existing advisories in
  transitive frontend packages (Next.js/sharp, zod, etc.); the lockfile is
  user-owned and was not changed, so an upgrade is left as a follow-up.
  `pip-audit` is not installed in the local environment, so the Python
  dependency audit is documented as not run.

## Tests (10.1)

- **Unit coverage:** the existing unit suites were extended rather than
  duplicated — chunker edge cases (empty/whitespace input, auto strategy
  selection, exact window boundaries and invalid settings), RRF (empty/single
  rankings, effect of `k`, duplicate metadata and score clamping), prompt
  builder (already covered context budgeting, delimiters, citation mapping and
  injection neutralization), provider adapters (Ollama NDJSON streaming,
  payload building, error propagation and registry registration) and encryption
  (tampering, wrong/malformed keys, empty and unicode values). 47 focused unit
  tests pass in those modules.
- **Real Postgres:** `apps/api/tests/test_postgres_integration.py` runs Alembic
  against a live PostgreSQL database and asserts behavior SQLite cannot
  reproduce: pgvector distance/tsvector search, generated `search_vector`,
  `SET NULL` audit foreign keys after account deletion, and feedback uniqueness
  plus `ON DELETE CASCADE`. It prefers `TEST_DATABASE_URL`, otherwise starts a
  `pgvector/pgvector:pg16` testcontainer, and skips cleanly when neither is
  available. `docker-compose.test.yml` provides a ready-to-use database.
  Declared dev deps: `testcontainers[postgres]` and `asyncpg`. Four tests are
  collected; they skip locally without Docker.
- **Tenant isolation:** `test_every_workspace_endpoint_is_tenant_isolated`
  enumerates all 29 workspace-scoped routes — including documents, chat,
  conversations, search, feedback, usage, analytics, audit log and export —
  and asserts a non-member gets 403 on each, that foreign resource ids do not
  resolve in the caller's workspace (404), and that the other tenant's data is
  unchanged.
- **End-to-end:** Playwright specs in `apps/web/e2e` cover signup (including
  weak-password rejection), upload (reaches `ready` and stays in its workspace)
  and chat (assistant turn plus feedback submission). They are kept out of the
  Next.js type-check with a dedicated `e2e/tsconfig.json` and discovered with
  `pnpm --filter web e2e`; setup and prerequisites are in `e2e/README.md`.
- **Verification:** ruff, format and mypy clean; `173 passed, 4 skipped`
  backend tests; `pnpm check-types`, `pnpm lint`, `pnpm build`, the e2e
  type-check and `playwright test --list` (6 tests) all pass.
