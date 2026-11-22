## Storage and search

| Decision | Why it fits | Alternative and upside | Tradeoff and when to revisit |
| --- | --- | --- | --- |
| PostgreSQL is authoritative, Qdrant is a derived vector index | SQL transactions own membership and canonical data. A dedicated vector index can scale independently and supports several dimensions. | PostgreSQL with pgvector alone simplifies operations, transactions, and backups. | Two stores need sync and recovery. Use the PostgreSQL path where one compatible profile and a smaller corpus meet the latency target. |
| Use relational data and vector similarity | Questions usually need relevant passages from documents with known ownership and references. | A graph database models multi-hop relationships and supports traversals. | A graph requires extracting and maintaining entity relationships and does not replace embeddings for semantic text search. Revisit for relationship-heavy queries backed by a real graph evaluation set. |
| Combine keyword and dense search with rank fusion | Exact identifiers and natural-language paraphrases can both surface. | Dense-only simplifies retrieval. An Elasticsearch or OpenSearch deployment offers more text analysis and independent search scaling. | Dense-only can miss rare terms. A dedicated text cluster adds synchronization and operations. Revisit when Postgres text search or language behavior limits measured retrieval. |
| Keep originals in object storage | Originals and generated records have different access patterns and lifecycles. | Store blobs in PostgreSQL for one transactional backup, or use a local filesystem for a single installation. | Larger relational backups or host-local files complicate growth and multi-process operation. Keep separate backup and restore procedures for objects. |

## Runtime and product decisions

| Decision | Why it fits | Alternative and upside | Tradeoff and when to revisit |
| --- | --- | --- | --- |
| FastAPI and Next.js split | Python suits extraction and retrieval. React and App Router support the workspace and public docs. | A single full-stack runtime shares tooling and type contracts. | Moving document tooling may cost more than maintaining two lockfiles. Current OpenAPI generation reduces drift. |
| Redis and a separate ARQ worker | Upload requests can finish while OCR, embedding and indexing proceed with independent lifecycle and progress. | Synchronous ingestion uses fewer components. A durable workflow engine offers stronger orchestration and visibility. | Synchronous requests time out under long jobs. A workflow engine adds infrastructure. Revisit when retry and repair across stores become more complex. |
| Poll indexing snapshots, stream chat over SSE | Reopening Documents can recover status immediately. SSE suits one-way token and source events. | WebSockets enable bidirectional event updates. | Persistent connections require subscription state and reconnect handling. Revisit for collaborative sessions or real-time worker events across a large installation. |
| Local CLI and remote API adapters | A local installation can reuse existing login and models. Hosted deployments can use explicit API credentials. | A shared remote provider reduces host setup and offers consistent model access. | Remote requests carry operating cost and data-handling requirements. CLI execution depends on the host account and is opt-in. |
| Static public docs in the app | Documentation is versioned with implementation and can be served without the API. | An external docs platform provides editorial workflows and independent publishing. | A second deployment and design system cost maintenance. Revisit if docs need independent contributors or release cycles. |

## Open engineering questions

- Calibrate abstention on unsupported questions and track citation accuracy separately from retrieval rank.
- Evaluate multilingual embeddings, OCR language packs, keyword behavior and mixed-language corpora together.
- If running more than one API replica, move generation cancellation to shared coordination and verify disconnect semantics.
- Exercise Qdrant recovery and embedding profile switching with representative data volumes.
