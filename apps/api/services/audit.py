"""Append-only audit trail for sensitive actions."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from models import AuditLog, User


async def record(
    session: AsyncSession,
    actor: User,
    action: str,
    *,
    workspace_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: object = None,
    details: dict | None = None,
) -> AuditLog:
    """Add an audit row to the current transaction (no commit here)."""
    entry = AuditLog(
        workspace_id=workspace_id,
        user_id=actor.id,
        actor_email=actor.email,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=details,
    )
    session.add(entry)
    await session.flush()
    return entry
