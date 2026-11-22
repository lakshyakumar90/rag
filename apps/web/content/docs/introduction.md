## What RAG Workspace does

RAG Workspace lets a team turn files and imported sources into a searchable knowledge base. A question retrieves relevant excerpts first. The selected model uses that evidence to answer, and the chat surfaces citations you can open to inspect the original snippet, page and heading when available.

| If you want to | Start here |
| --- | --- |
| Run the app or connect an existing local AI tool | [Installation and setup](/docs/setup) |
| Upload a document and follow its progress | [Using a workspace](/docs/workspace) |
| Understand services and find code | [Architecture](/docs/architecture) and [file guide](/docs/repository) |
| Explore the design visually | [Interactive floorplan](/docs/floorplan) |
| Understand why a dependency was chosen | [Decisions and alternatives](/docs/decisions) |

## Public docs and private workspaces

Anyone who can reach the web deployment can read these pages and the floorplan without an account. Signing into a workspace is required to use its documents, conversations, settings and usage data. The floorplan describes repository structure and request flows.

## The short version

The web app is built with Next.js and the API with FastAPI. Redis queues document processing, S3-compatible storage holds original files, and PostgreSQL holds workspaces, permissions, conversations and chunk data. Qdrant provides a configurable vector index alongside PostgreSQL keyword search. Embeddings and answer generation use separate providers, so local Ollama embeddings can be paired with a host Codex or OpenCode CLI.
