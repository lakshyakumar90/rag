# Backup and restore

A usable backup has **two halves**: the Postgres database (workspace, document, chunk, vector and conversation rows) and the S3-compatible object store that the app accesses through the MinIO SDK (the original uploaded files). A database row whose object is missing, or an orphan object with no row, is not a working document. Always capture both halves at the same time and restore them as a pair.

The commands below use the Compose service names (`postgres`, `minio`) and the credentials already in `.env`. They never put a password on the command line: the container environment supplies `POSTGRES_*`, and the shell sources `.env` for the AWS CLI. Add `-f docker-compose.prod.yml` to every `docker compose` command for the production stack; the service names are the same in the development stack. Run from the repository root. POSIX shell syntax is shown; on Windows use WSL, Git Bash, or an equivalent `mc` container with `--env-file .env`.

## What must be backed up

| Store | Contents | Compose service | Volume |
|---|---|---|---|
| Postgres 16 + pgvector | users, workspaces, memberships, documents, chunks + embeddings, conversations, messages, feedback, audit log | `postgres` | `postgres_data` |
| Object storage | original uploads under `<workspace_id>/<uuid>` | `minio` | `minio_data` |

Redis is intentionally not backed up: rate-limit counters and ARQ jobs are ephemeral, and pending jobs can be re-enqueued from the `pending`/`processing` document rows if needed.

## Postgres: logical backup with `pg_dump`

```bash
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)

# Custom-format dump (-Fc): compact, supports parallel restore and pg_restore -l.
docker compose -f docker-compose.prod.yml exec -T postgres \
  sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "backups/postgres-$STAMP.dump"

# List the archive contents to confirm the dump is readable.
pg_restore -l "backups/postgres-$STAMP.dump" | head
```

`pg_dump` includes the `CREATE EXTENSION` statement for pgvector and the schema/data for all tables. Keep the `.dump` file outside the Compose volumes and copy it to off-host storage.

## Postgres: restore with `pg_restore`

Stop writers first so no new rows are added during the restore, then restore into the *same* database and re-apply migrations if the dump predates the current head.

```bash
docker compose -f docker-compose.prod.yml stop api worker

docker compose -f docker-compose.prod.yml exec -T postgres \
  sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --exit-on-error' \
  < backups/postgres-YYYYMMDD-HHMMSS.dump

# Only needed if the backup is older than the current schema:
docker compose -f docker-compose.prod.yml run --rm migrate

docker compose -f docker-compose.prod.yml start api worker
```

`--clean --if-exists` drops existing objects before recreating them; harmless warnings about objects that do not exist yet can be ignored. Restoring into a *different* database is done by overriding `POSTGRES_DB` in the environment — do not inline credentials in the command.

## Object storage: mirror the bucket

The shipped stack uses an S3-compatible service (LocalStack) behind the same
`MINIO_*` settings the app uses with the MinIO SDK. Back up the object store
with the AWS CLI, which is already present in the LocalStack image:

```bash
set -a; . ./.env; set +a   # load MINIO_* values without printing secrets

# Full object backup (repeat with the same $STAMP as the DB dump).
docker compose -f docker-compose.prod.yml run --rm --entrypoint aws minio \
  --endpoint-url http://minio:4566 s3 sync "s3://${MINIO_BUCKET:-rag}" \
  "/backups/objects-$STAMP/"

# Restore: --delete removes objects created after the backup.
docker compose -f docker-compose.prod.yml run --rm --entrypoint aws minio \
  --endpoint-url http://minio:4566 s3 sync "/backups/objects-YYYYMMDD-HHMMSS/" \
  "s3://${MINIO_BUCKET:-rag}/" --delete
```

Mount a backup directory into the `minio` service if you use this approach in
production (the Compose file does not publish the object store to the host).
A sync is an incremental-friendly copy of the whole bucket, not a versioned
snapshot, so pair every sync with a database dump taken at the same time.

**If you swap in a real MinIO server**, the same data can be mirrored with
`mc`; note that MinIO's community images were retired from the public
registries, so supply your own image/endpoint:

```bash
mc alias set rag-local "http://localhost:${MINIO_PORT:-9000}" \
  "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc mirror "rag-local/${MINIO_BUCKET:-rag}" "backups/minio-$STAMP/"
mc mirror --overwrite "backups/minio-YYYYMMDD-HHMMSS/" \
  "rag-local/${MINIO_BUCKET:-rag}/"
```

Inside the Compose network the endpoint is `http://minio:4566` for LocalStack
(or `http://minio:9000` for a real MinIO).

## Suggested schedule and retention

| Backup | Frequency | Retention |
|---|---|---|
| Postgres custom-format dump | Daily, plus immediately before migrations or upgrades | 7 daily, 4 weekly, 12 monthly |
| Object-store sync | Weekly, plus before any bulk delete | 4 weekly, 12 monthly |
| Off-host/encrypted copy | After each successful backup | Same as above, in a separate failure domain |

Automate with a cron job or a scheduled container that writes to a mounted backup volume, and alert on failure or when the newest archive is older than the expected interval. Encrypt archives at rest and restrict access: the dump contains password hashes, encrypted provider keys and document text.

## Restore drill checklist

Run this on a throwaway stack or a scratch database/ bucket, not on production data.

- [ ] Confirm the archive: `pg_restore -l <dump>` succeeds and `aws s3 ls --recursive` shows the expected object count.
- [ ] Note the timestamps of the DB dump and object-store sync; they must match.
- [ ] Stop `api` and `worker` so nothing writes during the restore.
- [ ] Restore Postgres, then the object store into the same bucket name; apply `alembic upgrade head` if needed.
- [ ] Start the stack and check `/health` and `/health/db`.
- [ ] Log in, open a known document, verify its text and citation snippets, and ask a question with a known answer.
- [ ] Check that a recently deleted item stays deleted and that the audit log is intact.
- [ ] Record the drill date, duration, issues and the RPO/RTO actually achieved.

## Deletion and audit semantics

Deleting an account removes its storage objects, owned workspaces, documents, conversations, memberships, invitations, provider configs and refresh tokens. It does **not** erase history: `AuditLog` is append-only, and its `user_id`/`workspace_id` foreign keys use `ON DELETE SET NULL`, so the redacted row (with `actor_email`, action and details) survives. Restoring an older backup therefore also restores audit rows that may postdate a later deletion — account deletion is not a GDPR-style erasure of the audit trail.
