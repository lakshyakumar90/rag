## Public and authenticated routes

`/docs`, its subpages and `/floorplan` are static public routes. They read repository-authored content during the build, without a workspace account or backend. Sign-in, registration and invitation acceptance serve as public entry points to the authenticated application. Workspace API endpoints enforce identity and membership independently of the client route guard.

## Identity and roles

`api/v1/dependencies.py` resolves a current user and workspace context. Auth services issue access tokens and rotate refresh tokens using a session cookie. Production deployments should use HTTPS, secure cookies and a correctly scoped origin. The owner, admin and member roles control workspace-level actions. Membership changes and last-owner protections are enforced in backend services.

## Document visibility

An accessible workspace can contain restricted documents. Explicit grants and workspace visibility govern which chunks a user can retrieve. `services/document_access.py` and the retrieval repository apply those rules. Qdrant is a retrieval accelerator and candidate IDs must still resolve to permitted PostgreSQL rows. Keep the storage, cache and indexing interfaces internal to the deployment.

## Provider credentials and network boundaries

Provider keys are encrypted using the configured application master key. Keep the database backups and key backups separately protected. CLI execution and local endpoints are opt-in and intended for a trusted local deployment. Remote source imports and configurable endpoints are subject to network restrictions. Enforce network egress policy in your deployment too, especially when accepting tenant-supplied URLs.
