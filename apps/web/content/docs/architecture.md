## Runtime topology

```text
Browser
  │
  └── Caddy (full Compose)
        ├── Next.js
        │     ├── /docs and /floorplan · public static documentation
        │     └── /workspaces/* · authenticated application
        └── /api/* ── FastAPI ────── PostgreSQL / Qdrant
                           │         S3-compatible object store
                           ├──────── LLM API or host CLI
                           └── Redis ── ARQ worker
                                         ├── object store
                                         ├── embedding provider
                                         └── PostgreSQL / Qdrant
```

Host mode runs the web server, API and worker as separate processes and can bypass Caddy. Their network endpoints are explicit configuration. In Compose, service names resolve on the internal network.

## Ingestion sequence

```text
Browser → FastAPI → original file in object storage
                 → PostgreSQL document row
                 → Redis queue → ARQ worker → extract → chunk
                                            → embed → persist → index
Browser ← status and progress snapshots ← FastAPI ← worker progress
```

The worker performs long-running work separately from the request that accepts a source. Its writes update durable document state. Polling provides the browser a current snapshot and allows users to reopen the documents page mid-job.

## Answer sequence

```text
Browser → authorized chat request
        → readable-document scope → vector search + keyword search
        → fuse ranks / optional rerank → bounded source context
        → model → SSE events → text + citation snippets
        → conversation and message records in PostgreSQL
```

Qdrant point identifiers locate chunks. PostgreSQL supplies canonical rows and authorization. Keeping retrieval behind the API gives the browser a small, consistent contract for both API-backed and CLI-backed models.

## Dependency direction

Routes validate input and resolve identity. Services enforce rules and coordinate work. Repositories construct queries and models describe persistent state. Provider adapters isolate network, storage and subprocess details. ARQ workers reuse the API's Python models and providers and can be run as a separate process. [Explore these boundaries on the floorplan](/floorplan).
