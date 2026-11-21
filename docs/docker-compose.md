# Docker Compose (Local Development)

This stack provides local infrastructure for the RAG app.

## Services

| Service | Image | Ports | Notes |
|---|---|---:|---|
| Postgres | `pgvector/pgvector:pg16` | `5432` | Named volume `postgres_data`; pgvector extension available in image |
| Redis | `redis:7-alpine` | `6379` | AOF persistence via `redis_data` volume |
| Object storage (S3) | `localstack/localstack:latest` | `9000` on host → `4566` in the network | `minio_data` volume; no console port |
| Bucket init | `localstack/localstack:latest` | — | One-shot container; creates `${MINIO_BUCKET:-rag}` with `aws` after the service is healthy |
| Ollama | `ollama/ollama:latest` | `11434` | `ollama_data` volume; models persist in volume |

All long-running services have healthchecks. Bucket creation waits for the S3 service to become healthy. MinIO's community images were retired from the public registries, so the stack uses LocalStack's S3 API; the application still talks to it with the MinIO SDK (`MINIO_HOST=minio`, container port `4566`).

## Start

```bash
docker compose up -d
```

Check status:

```bash
docker compose ps
```

## Ollama model pull (documented)

The Ollama service is started by Compose, but the embedding model is **not** pulled automatically (pulls can be large/slow). Pull the model used by this project (see `docs/decisions.md`):

```bash
docker compose exec ollama ollama pull embeddinggemma-2:440m
```

If your Ollama registry uses a different tag for the selected model, substitute the exact tag (decision record currently specifies `embeddinggemma-2:440m`; confirm the exact Ollama tag with `ollama list` / your Ollama catalog and update the command/docs accordingly).

Verify:

```bash
docker compose exec ollama ollama list
curl http://localhost:11434/api/tags
```

## Environment overrides

Defaults work for local development. You can override via `.env` or shell variables (see `.env.example`): `POSTGRES_*`, `REDIS_PORT`, `MINIO_*`, `MINIO_BUCKET`, `OLLAMA_PORT`.

The app's `Settings` reads the same `.env` (repo root), so `POSTGRES_*` values stay in sync between Compose and the API.

### Port 5432 already in use

If another PostgreSQL (e.g., a native Windows service) owns 5432, Compose cannot bind it. Set a free port in `.env` instead:

```bash
# .env
POSTGRES_PORT=5433
POSTGRES_HOST=127.0.0.1
```

Then restart Compose (`docker compose up -d postgres`). `POSTGRES_HOST=127.0.0.1` also avoids a slow `::1` (IPv6) fallback, since Compose publishes the port on IPv4 only.

## Stop / reset

```bash
docker compose down
# remove volumes/data
docker compose down -v
```
