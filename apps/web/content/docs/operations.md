## Service checks

| Symptom | Where to investigate |
| --- | --- |
| Public docs fail but the API works | Check Next.js and Caddy routing. The docs have no API dependency. |
| Upload succeeds but remains queued | Check Redis connectivity, ARQ worker health and worker logs. |
| A scan yields little text | Confirm Tesseract, the configured language packs and the PDF page quality. |
| Embedding errors or missing vectors | Check the exact model tag, Ollama or provider reachability and vector dimensions. |
| Qdrant unavailable or out of sync | Check `QDRANT_URL`, enablement, collection dimensions and synchronization state. |
| CLI connection fails | Check executable resolution, login, model availability and the API process account. |
| Login loops | Check web/API origins, cookie settings and the browser hostname. |

## Qdrant rollout and repair

Keep PostgreSQL and object storage intact. Review `scripts/backfill_qdrant.py --help` before repairing an index. Point migration and backfill commands at the same environment as the API. Run a dry run where supported, backfill existing eligible rows, check counts and representative retrieval, then enable Qdrant with `QDRANT_ENABLED=true`. The configured compatible pgvector fallback can cover some service failures. Investigate errors and fix synchronization before treating the index as healthy.

## Backup and recovery

Back up PostgreSQL, the source bucket and runtime secrets separately. Store encryption keys securely because provider credentials require the matching key to decrypt. Take Qdrant snapshots when recovery time requires them, or rebuild vectors from canonical records and the matching embedding provider. Redis can hold queued work, so include it in the recovery plan if preserving pending jobs matters.

Restore into a separate environment first. Apply the correct schema migrations, verify objects and grant rules, rebuild or restore vectors, and run real retrieval and citation checks before promoting the instance. See `docs/backup.md` for repository runbook details.

## Regenerate the floorplan

Use a local checkout of the upstream Floorplan tool and run:

```text
node scripts/generate-floorplan.mjs <checkout>/skills/floorplan
```

The generator builds from Git-tracked files, including staged additions. It exports the graph and flows without bundling source file bodies or local credentials. Review the exported HTML before committing it along with any map changes.
