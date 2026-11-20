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
