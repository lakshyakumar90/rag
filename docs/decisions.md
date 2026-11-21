# Decisions

## Embedding Model

- **Choice:** `embeddinggemma-2:440m` (served via Ollama)
- **Purpose:** Text embeddings for the RAG pipeline
- **Embedding dimension:** _Verify from the model/runtime (e.g., inspect an embedding response or run `ollama show embeddinggemma-2:440m`) and record the confirmed value here._
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
