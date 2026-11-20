"""ORM model tests: normalization, constraints, enums and cascades."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.security import hash_password
from models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    User,
    Workspace,
)


async def _user(factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with factory() as session:
        user = User(
            email="Owner@Example.com", password_hash=hash_password("StrongPassw0rd!")
        )
        session.add(user)
        await session.commit()
        return user.id


async def _workspace(
    factory: async_sessionmaker[AsyncSession], owner_id: uuid.UUID
) -> uuid.UUID:
    async with factory() as session:
        workspace = Workspace(
            name="  Acme Corp ", slug="  ACME-Corp ", created_by=owner_id
        )
        session.add(workspace)
        await session.commit()
        return workspace.id


async def test_workspace_normalizes_name_and_slug(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = await _user(session_factory)
    workspace_id = await _workspace(session_factory, owner_id)
    async with session_factory() as session:
        workspace = await session.get(Workspace, workspace_id)
        assert workspace is not None
        assert workspace.name == "Acme Corp"
        assert workspace.slug == "acme-corp"
        assert workspace.created_by == owner_id


async def test_workspace_rejects_invalid_slug(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = await _user(session_factory)
    async with session_factory():
        with pytest.raises(ValueError, match="slug"):
            Workspace(name="Bad", slug="Not A Slug!", created_by=owner_id)


async def test_workspace_slug_is_unique(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = await _user(session_factory)
    await _workspace(session_factory, owner_id)
    async with session_factory() as session:
        session.add(Workspace(name="Another", slug="acme-corp", created_by=owner_id))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_membership_unique_per_user_and_workspace(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = await _user(session_factory)
    workspace_id = await _workspace(session_factory, owner_id)
    async with session_factory() as session:
        session.add(
            Membership(
                user_id=owner_id, workspace_id=workspace_id, role=MembershipRole.OWNER
            )
        )
        await session.commit()

    async with session_factory() as session:
        session.add(
            Membership(
                user_id=owner_id, workspace_id=workspace_id, role=MembershipRole.MEMBER
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_membership_role_round_trips_as_enum(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = await _user(session_factory)
    workspace_id = await _workspace(session_factory, owner_id)
    async with session_factory() as session:
        session.add(
            Membership(
                user_id=owner_id, workspace_id=workspace_id, role=MembershipRole.ADMIN
            )
        )
        await session.commit()

    async with session_factory() as session:
        membership = (
            await session.execute(text("SELECT role FROM memberships"))
        ).scalar_one()
        assert membership == "admin"
        orm = (await session.execute(select(Membership))).scalar_one()
        assert orm.role is MembershipRole.ADMIN


async def test_membership_rejects_unknown_role(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = await _user(session_factory)
    workspace_id = await _workspace(session_factory, owner_id)
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO memberships (id, created_at, updated_at, user_id, "
                    "workspace_id, role) VALUES (:id, CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP, :uid, :wid, 'superuser')"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "uid": str(owner_id),
                    "wid": str(workspace_id),
                },
            )


async def test_invitation_defaults_and_email_normalization(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = await _user(session_factory)
    workspace_id = await _workspace(session_factory, owner_id)
    async with session_factory() as session:
        invitation = Invitation(
            email="  Invitee@Example.com ",
            workspace_id=workspace_id,
            role=MembershipRole.MEMBER,
            token_hash="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        session.add(invitation)
        await session.commit()
        invitation_id = invitation.id

    async with session_factory() as session:
        loaded = await session.get(Invitation, invitation_id)
        assert loaded is not None
        assert loaded.email == "invitee@example.com"
        assert loaded.status is InvitationStatus.PENDING
        assert loaded.role is MembershipRole.MEMBER
        assert loaded.token_hash == "a" * 64


async def test_invitation_token_hash_is_unique(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = await _user(session_factory)
    workspace_id = await _workspace(session_factory, owner_id)
    values: dict[str, Any] = {
        "workspace_id": workspace_id,
        "role": MembershipRole.MEMBER,
        "token_hash": "b" * 64,
        "expires_at": datetime.now(UTC) + timedelta(days=1),
    }
    async with session_factory() as session:
        session.add(Invitation(email="one@example.com", **values))
        await session.commit()
    async with session_factory() as session:
        session.add(Invitation(email="two@example.com", **values))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_deleting_workspace_cascades_to_memberships_and_invitations(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = await _user(session_factory)
    workspace_id = await _workspace(session_factory, owner_id)
    async with session_factory() as session:
        session.add(
            Membership(
                user_id=owner_id, workspace_id=workspace_id, role=MembershipRole.OWNER
            )
        )
        session.add(
            Invitation(
                email="invitee@example.com",
                workspace_id=workspace_id,
                role=MembershipRole.MEMBER,
                token_hash="c" * 64,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        workspace = await session.get(Workspace, workspace_id)
        assert workspace is not None
        await session.delete(workspace)
        await session.commit()

    async with session_factory() as session:
        assert (
            await session.execute(text("SELECT count(*) FROM memberships"))
        ).scalar_one() == 0
        assert (
            await session.execute(text("SELECT count(*) FROM invitations"))
        ).scalar_one() == 0
