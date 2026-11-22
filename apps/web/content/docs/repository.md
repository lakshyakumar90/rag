## Folder structure

```text
rag/
├── apps/
│   ├── api/                 FastAPI backend and ARQ worker
│   │   ├── api/v1/          Routing, request dependencies and endpoints
│   │   ├── core/            Configuration, security and shared primitives
│   │   ├── models/          Database tables and column types
│   │   ├── repositories/    Database access and search queries
│   │   ├── schemas/         Typed API inputs and outputs
│   │   ├── services/        Application use cases
│   │   ├── providers/       External service and CLI adapters
│   │   ├── workers/         Extraction, OCR, indexing and profile jobs
│   │   ├── alembic/         Schema migrations
│   │   └── tests/           Python tests
│   └── web/                 Next.js workspace and public docs
│       ├── app/             Route entry points and layout
│       ├── components/      Shared UI, providers and authentication guard
│       ├── content/docs/    Markdown for the public site
│       ├── lib/             Typed API and streaming clients
│       ├── public/          Static assets and Floorplan export
│       └── e2e/             Playwright specs
├── docs/                    Engineering runbooks and Floorplan source
├── evals/                   Evaluation code, corpus and historical results
├── packages/                Shared UI, lint and TypeScript configuration
└── scripts/                 Setup, demo data, backfill and map export
```

## Web files

| File | Purpose |
| --- | --- |
| `apps/web/app/layout.tsx` | Root document, fonts, global providers and toaster |
| `apps/web/app/page.tsx` | Session-aware entry into login or dashboard |
| `apps/web/app/login/page.tsx`, `register/page.tsx` | Login and account creation |
| `apps/web/app/dashboard/page.tsx` | Workspace dashboard |
| `apps/web/app/invitations/accept/page.tsx` | Invitation acceptance |
| `apps/web/app/workspaces/[workspaceId]/layout.tsx` | Workspace route shell |
| `workspaces/[workspaceId]/chat/page.tsx` | Conversation sidebar, composer, message actions and citation display |
| `workspaces/[workspaceId]/documents/page.tsx` | Uploads, imports, status, reindexing and grants |
| `workspaces/[workspaceId]/settings/page.tsx` | Provider selection defaults, tests and embedding settings |
| `workspaces/[workspaceId]/members/page.tsx`, `usage/page.tsx` | Membership and administrative usage views |
| `apps/web/components/auth-guard.tsx`, `lib/auth/auth-provider.tsx`, `lib/auth-client.ts` | Session gate, browser auth state and API token behavior |
| `apps/web/lib/api/client.ts`, `openapi.json`, `schema.d.ts` | API request layer, exported spec and generated schema types |
| `apps/web/lib/chat-stream.ts`, `agent-stream.ts`, `progress.ts` | Answer events, tool events and ingestion progress presentation |
| `apps/web/app/(public-docs)/` | Public layout, navigation, search, Markdown routes and full-screen map |

## API entry points and use cases

Paths in these tables are relative to `apps/api/`.

| File or group | Purpose |
| --- | --- |
| `main.py`, `api/v1/router.py` | Starts FastAPI and assembles the versioned router |
| `api/v1/dependencies.py`, `cookies.py` | Resolves request identity and workspace scope and manages auth cookies |
| `api/v1/endpoints/auth.py`, `account.py`, `users.py` | Account authentication and profile actions |
| `api/v1/endpoints/workspaces.py`, `invitations.py` | Workspace lifecycle, membership and invitations |
| `api/v1/endpoints/documents.py`, `retrieval.py` | Uploads, imports, indexing status, grants and evidence retrieval |
| `api/v1/endpoints/chat.py`, `conversations.py`, `agent.py` | Streamed or complete answers, history, stop/regenerate and tool sessions |
| `api/v1/endpoints/ai.py`, `cli.py`, `provider_configs.py`, `embedding_profiles.py` | Default model settings, CLI checks, provider credentials and reembedding |
| `api/v1/endpoints/production.py` | Usage, audit and feedback endpoints |
| `services/documents.py`, `sources.py`, `document_access.py` | Source lifecycle, remote import rules and document-level visibility |
| `services/chat.py`, `conversations.py`, `retrieval.py`, `query_cache.py` | Answer lifecycle, ranking, caching and conversation history |
| `services/agent.py`, `agent_tools.py`, `core/calculator.py` | Bounded tool loop, tool registry and arithmetic |
| `services/qdrant_index.py`, `embedding_profiles.py` | Synchronization with the vector index and profile lifecycle |
| `services/feedback.py`, `audit.py`, `usage.py` | Feedback, activity events and aggregate reporting |
| `core/config.py`, `database.py`, `redis.py` | Settings, database engine and Redis connection |
| `core/security.py`, `crypto.py`, `net.py`, `rate_limit.py` | Auth primitives, credential encryption, URL checks and throttling |
| `core/progress.py`, `prompting.py`, `rrf.py` | Progress model, evidence prompt construction and fusion |
| `core/exceptions.py`, `middleware.py`, `security_headers.py`, `logging.py` | Error envelopes, request handling and health of runtime observability |

## API persistence, providers and jobs

| File or group | Purpose |
| --- | --- |
| `models/document.py`, `types.py`, `qdrant.py` | Document and chunk state, DB representations, embedding and sync records |
| `models/access.py`, `membership.py`, `workspace.py`, `invitation.py` | ACLs, memberships, tenants and invitations |
| `models/conversation.py`, `ai.py`, `provider_config.py` | Chat data, AI settings and provider records |
| `models/user.py`, `refresh_token.py`, `production.py` | Account, refresh, feedback, audit and usage data |
| `repositories/retrieval.py`, `documents.py` | Ranking candidate queries, access scope and document/chunk persistence |
| `repositories/*.py`, `schemas/*.py` | Entity-specific queries and API contracts named by domain |
| `alembic/env.py`, `alembic/versions/` | Migration runtime and versioned schema changes, identified by filename |
| `providers/embeddings.py`, `qdrant.py`, `rerank.py` | Embedding, vector and optional reranker clients |
| `providers/storage.py`, `minio.py`, `queue.py` | Object storage abstraction, S3-compatible adapter and Redis queue |
| `providers/llm/`, `providers/cli/` | Generation adapter registries and provider-specific implementations |
| `workers/settings.py`, `source_ingest.py`, `ingest.py`, `profile_switch.py` | Worker entry point, import, index and profile reembedding jobs |
| `workers/extraction.py`, `ocr.py`, `chunking.py`, `tokenization.py` | Source reading, OCR, chunk boundaries and approximate tokens |
| `export_openapi.py`, `tests/` | Generates the API spec and tests the backend by domain |

## Root files and tooling

| File or group | Purpose |
| --- | --- |
| `docker-compose.yml`, `docker-compose.override.yml` | Development services and development overrides |
| `docker-compose.prod.yml`, `docker-compose.test.yml`, `Caddyfile` | Full deployment, test infrastructure and reverse proxy rules |
| `.env.example`, `scripts/generate_secrets.py` | Configuration contract and fresh secret generation |
| `scripts/seed_demo.py`, `scripts/backfill_qdrant.py` | Demo workspace data and repair or migration of vector sync |
| `docs/floorplan/architecture.json`, `scripts/generate-floorplan.mjs` | Interactive architecture graph and offline export generator |
| `pyproject.toml`, `uv.lock`, `pyrightconfig.json` | Python dependencies, tool configuration and type checking |
| `package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `turbo.json` | JavaScript workspaces, dependency lock and task graph |
| `packages/ui/`, `packages/eslint-config/`, `packages/typescript-config/` | Shared UI building blocks and monorepo tooling |
| `.github/workflows/ci.yml`, `.github/dependabot.yml` | Pipeline checks and dependency update policy |
