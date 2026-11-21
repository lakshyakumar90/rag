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
