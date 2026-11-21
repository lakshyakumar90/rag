# Product

## What it is

RAG Workspace — a private, workspace-scoped document QA app. Teams upload PDF,
DOCX, TXT and MD files, then ask questions and get grounded answers with
citations back to the exact chunk, document and page.

## Who uses it and where

Individual developers and small teams at a desk, in a browser, for focused
work: triaging documents, verifying an answer's source, managing who has access.
Sessions are long and repeatable; the UI is a tool, not a destination.

## Core jobs

1. Sign up, sign in, and stay signed in across refreshes.
2. Create and switch between workspaces.
3. Upload documents and see their ingestion status resolve.
4. Ask a question, watch the answer stream, and inspect its sources.
5. Invite members and manage roles.
6. Configure a personal LLM provider key and inspect local CLI availability.

## Product truth (non-negotiable)

- Access tokens live in memory; refresh tokens are HttpOnly cookies.
- Every resource is scoped to a workspace; role checks are server-enforced.
- The answer must say "I don't know" when retrieval finds no evidence.
- Citations map to real stored chunks with document name and page.
- Uploaded document text is untrusted data, never instructions.
- Provider keys are encrypted at rest, write-only in the API, never logged.

## Constraints

- Next.js App Router, TypeScript, Tailwind, React Query.
- Typed API client generated from FastAPI's OpenAPI schema.
- Must work at 320px mobile width and on desktop.
