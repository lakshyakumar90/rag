## Verification layers

| Scope | Command or source | What it covers |
| --- | --- | --- |
| Backend tests | `uv run pytest -q` from the root | Auth, ACLs, ingestion, retrieval, adapter behavior, streaming and progress |
| Real PostgreSQL | `apps/api/tests/test_postgres_integration.py` | Migrations and database-specific vector, FTS and persistence behavior with a supported PostgreSQL instance |
| Web validation | `pnpm --filter web lint`, `pnpm --filter web check-types`, `pnpm --filter web build` | Lint rules, TypeScript and static route generation |
| Browser flows | `pnpm --filter web e2e` | Workspace journeys in a configured test environment |
| Public documentation | Open `/docs`, a nested page, `/docs/floorplan` and `/floorplan` signed out | Navigation, map asset, responsive layout and no authentication requirement |

After changing API contracts, run `pnpm --filter web api:types` and check the OpenAPI and generated type changes together. Test permission scenarios using multiple accounts. Mocks and SQLite exercise many rules, while real service checks cover network behavior and native SQL operators.

## Retrieval evaluation

`evals/evaluate.py` runs questions over the controlled corpus. `evals/questions.jsonl` records the evaluation set and `evals/results.json` is a historical snapshot. Read `docs/evaluation.md` for the corpus, metrics and known defects. Measure retrieval ordering, answer abstention, and citation correctness independently. Record the embedding profile, chunk settings and cache state when comparing runs.

`evals/multilingual.py` gives a starting point for language-specific evaluation. Extend it with the scripts, languages and source layouts you actually use. Separately test OCR on pages with known expected text and verify page-level citation coordinates after indexing.
