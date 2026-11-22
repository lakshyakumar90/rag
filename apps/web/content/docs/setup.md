## Choose how to run it

| Mode | Run in Docker | Run on the host |
| --- | --- | --- |
| Host development | PostgreSQL, Redis, S3-compatible storage and Qdrant | Next.js, FastAPI, ARQ, existing Ollama and any login-backed CLI providers |
| Full Compose | Caddy, Next.js, FastAPI, ARQ, migrations, PostgreSQL, Redis, object storage, Qdrant and Ollama | Docker and Compose |
| Docs development | No services required for the public pages | Next.js |

## Host development

Use the versions pinned in `package.json` and `pyproject.toml`. Install dependencies at the repository root with `pnpm install` and `uv sync`. Create a local `.env` using `.env.example` as the template and generate fresh credentials with `python scripts/generate_secrets.py`.

Start only the infrastructure you need.

```bash
docker compose up -d postgres redis minio minio-create-bucket qdrant
```

Use the host ports defined by Compose in your API configuration. Set `DATABASE_URL`, `REDIS_URL`, the object-store endpoint and credentials, and `QDRANT_URL` to their reachable host addresses. Apply migrations and run the API and worker in separate shells from `apps/api`.

```bash
uv run alembic upgrade head
uv run uvicorn main:app --host 127.0.0.1 --port 8000
uv run arq workers.settings.WorkerSettings
```

Set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1` in the web process environment and run `pnpm --filter web dev`. The package defaults to port 3000. If using a different port, include that exact origin in the API CORS settings and update web or invitation URLs as needed. Use the same browser hostname consistently for session cookies.

### Host Ollama and local CLIs

Check existing Ollama models with `ollama list`. Set `OLLAMA_BASE_URL=http://localhost:11434` and select the installed embedding model with `OLLAMA_EMBEDDING_MODEL`. The repository example uses `embeddinggemma-2:440m` with the 768-dimensional profile. Check the exact installed tag and dimensions before indexing. A host Ollama service takes the place of the Docker Ollama service in this mode.

Enable local CLI execution with `CLI_MODE_ENABLED=true` and `LOCAL_MODE_ENABLED=true`. Start the API under the user account with the CLI installations and logins. Verify Codex and OpenCode resolve from that same environment, or configure their executable paths using the settings in `.env.example`. Check model availability in **Settings** using **Test connection**.

## Full Compose

Generate fresh secrets, then run:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Caddy serves the web app and proxies API traffic. It also exposes the public docs through the same web hostname at `/docs` and `/floorplan`. The stack provisions its own Ollama by default. The host setup is the option for using your existing local CLIs and avoiding a second Ollama instance.

## Docs only

Run `pnpm --filter web dev` and open `/docs`. The docs are built from Markdown in `apps/web/content/docs`. The interactive map is a static HTML export that ships with the app.
