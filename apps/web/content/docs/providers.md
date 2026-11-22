## Generation and embeddings

Generation and embeddings are separate. Generation answers a chat request. Embeddings turn both chunks and queries into comparable vectors. You can run embeddings through Ollama while passing generation to Codex, OpenCode, an OpenAI-compatible endpoint or Anthropic. Changes to a chat model do not require reindexing when the embedding profile stays the same.

| Area | Where to look |
| --- | --- |
| Connection tests and active configuration | Workspace **Settings**, `api/v1/endpoints/cli.py` and `api/v1/endpoints/provider_configs.py` |
| Per-message provider and model | Chat composer and `services/ai_settings.py` |
| CLI commands and stream handling | `providers/cli/` |
| HTTP adapters and normalized streaming | `providers/llm/` |
| Embedding calls and profiles | `providers/embeddings.py`, `services/embedding_profiles.py`, `workers/profile_switch.py` |

## Local CLI connection checks

Codex defaults to `gpt-6-luna` in API configuration. Actual model availability depends on the installed CLI and account. OpenCode models depend on the providers configured in the host installation. Run the API in the same environment as the CLIs, pick a model the tool reports, and use **Test connection** in Settings. Confirm output from an actual chat when validating a new model or executable path.

## Switching embedding profiles

Record the provider, exact model and output dimension. Configure a profile with the matching dimension and reembed through the workspace profile switch. Qdrant partitions vectors by dimension and retrieval uses profile identity to keep spaces separate. Two models of the same dimension can still have incompatible vector spaces. Profile switching reindexes documents before flipping the workspace profile, so schedule large switches in a maintenance window and verify representative queries and access after completion.

## Agent loop

`services/agent.py` advances the conversation through bounded tool and model turns. `services/agent_tools.py` registers document search, a calculator, document summarization and web search when configured. Document tools apply workspace visibility. The browser consumes agent events in `lib/agent-stream.ts`. Tool support and provider behavior determine which combinations work, so test the actual model before enabling agent mode for a team.
