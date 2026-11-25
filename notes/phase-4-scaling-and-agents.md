# Phase 4 — Multi-Replica Scaling, RBAC Cache & Research Agent Notes

## Prompt 4.1: Redis Pub/Sub Cancel, RBAC-Safe Redis Cache & Email Invites (`fd5cea5`)
- **Changes**:
  - Added Redis Pub/Sub stream cancellation (`chat:cancel:<stream_id>`, `publish_cancel_stream`, `watch_redis_cancel`) in `apps/api/services/chat.py` so Stop/Regenerate works across multiple API replicas.
  - Refactored `apps/api/services/query_cache.py` to include `(workspace_id, auth_scope_hash, doc_filter_hash, top_k, profile_id, query_hash)` in exact keys, partition semantic cache buckets by `(workspace_id, auth_scope_hash, doc_filter_hash)`, and store entries in Redis with TTL eviction (`300s`) + workspace key-set invalidation.
  - Added `trusted_proxy_cidrs` in `apps/api/core/config.py` and CIDR peer verification in `apps/api/core/rate_limit.py` (`_is_trusted_proxy`).
  - Created `apps/api/services/invitations.py` with Resend API and SMTP email adapters for workspace invitation links.
- **Verification**: `apps/api/tests/test_scaling_phase4.py` + `test_query_cache.py` + `test_retrieval.py` + `test_streaming_chat.py` + `test_graph.py` (24/24 passed).

## Prompt 4.2: Agentic Multi-Step Research & Incremental GitHub Sync (`4011ce3`)
- **Changes**:
  - Bumped `agent_max_steps` from `4` to `8` in `apps/api/core/config.py` for Research Mode.
  - Added `decompose_query` (splits complex comparison queries into parallel sub-queries) and `self_critique_answer` in `apps/api/services/agent.py`.
  - Added `compare_documents(document_ids, criteria)` in `apps/api/services/agent_tools.py` returning a structured Markdown comparison table with inline `[n]` citations.
  - Added `fetch_github_incremental` and `IncrementalGitHubSyncResult` in `apps/api/services/sources.py` using GitHub's Compare API to fetch only modified text files since `last_synced_commit_sha`, track deletions, and skip unchanged/binary files.
- **Verification**: `apps/api/tests/test_research_agent_phase4.py` + `test_agent.py` + `test_sources.py` (12/12 passed).
