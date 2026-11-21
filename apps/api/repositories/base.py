"""Helpers shared by repositories that hold workspace-scoped data."""

import uuid


def ensure_workspace_scope(
    entity: str, actual_workspace_id: uuid.UUID, workspace_id: uuid.UUID
) -> None:
    """Guard a write against cross-tenant ORM objects.

    Read methods filter by ``workspace_id`` in SQL; write methods receive a
    loaded object instead, so they check the object's tenant before persisting.
    A mismatch is a programming error, not a user-facing validation failure.
    """
    if actual_workspace_id != workspace_id:
        raise ValueError(
            f"{entity} belongs to workspace {actual_workspace_id}, not {workspace_id}"
        )
