## Add and index a source

1. Sign in, open a workspace and go to **Documents**.
2. Upload a file or import a URL or public GitHub repository. Upload the ZIP file for a supported Notion export.
3. Follow the row status. Upload progress covers browser transfer. After upload, the indexing display follows the API's current phase and reports pages and chunks as they become known.
4. Once the source is ready, ask a question that should be answered by it. A failed row can be inspected and retried using reindex.

PDFs can retain page references. Markdown and DOCX can retain heading paths. Unpaginated content may have no page number.

## Ask and verify

In **Chat**, choose a provider and model in the composer. Send a question or a follow-up. Use the source chips under the answer to inspect the returned snippets. The answer action row contains feedback and regeneration controls where applicable. Stop is available while a stream is active. A connection test belongs under **Settings**, where it can use the configured provider and model.

Enable agent mode when you want available tools to help answer a question. The agent can search documents, calculate values, summarize an accessible document, or use configured web search. Regular chat follows the retrieval-and-answer pipeline.

## Share or restrict access

Invite teammates from **Members**. Workspace roles govern administrative capabilities. A document can be workspace-visible or restricted with explicit grants. After changing a grant, check the result using the account whose access changed.
