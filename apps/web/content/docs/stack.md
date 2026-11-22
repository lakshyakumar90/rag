## Application and developer tooling

| Technology | What it does | Cost of the choice |
| --- | --- | --- |
| Next.js App Router, React, TypeScript | Workspace application and statically rendered public docs | Two runtimes and strict server/client boundaries |
| Tailwind, Radix, Lucide | App styling, interactive controls and icons | Theme and responsive behavior need explicit verification |
| TanStack Query | Server-state queries and refreshes in the workspace | Query keys and invalidation are application contracts |
| FastAPI, Pydantic | HTTP endpoints, validation and OpenAPI | Python and TypeScript contracts must stay in sync |
| SQLAlchemy, Alembic | Persistence mappings, query composition and migrations | Schema changes need a reviewed migration and compatibility checks |
| pnpm, Turborepo, uv | JavaScript workspaces, task ordering and Python dependency management | Separate lockfiles and toolchains |
| pytest, Playwright | API/service coverage and browser journeys | Full coverage needs running infrastructure and real-engine checks |

## Data and AI infrastructure

| Technology | What it does | Cost of the choice |
| --- | --- | --- |
| PostgreSQL, pgvector, tsvector | Relational state, keyword search and a legacy vector path | Search and application data share database capacity |
| Qdrant | Dedicated vector collections by embedding dimension | Additional persistence, synchronization and backup concerns |
| Redis, ARQ | Jobs and shared infrastructure for rate limits and progress | Worker operations and queue monitoring |
| S3-compatible object storage | Stores originals outside the relational database | Bucket policy, credentials and independent backups |
| Ollama | Local embedding and optional generation | Model disk space, compute and tag management |
| Codex, OpenCode, Claude CLI adapters | Use supported host-installed and authenticated CLIs | Host environment and login affect availability |
| Tesseract | OCR for PDF pages with insufficient extracted text | Extra CPU and language-pack dependencies |
| Caddy, Docker Compose | Proxy a single web origin and orchestrate a reproducible stack | Compose remains a single-host deployment model |

See [Decisions and alternatives](/docs/decisions) for the changes that would justify swapping any of these.
