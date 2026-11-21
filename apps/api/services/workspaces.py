"""Workspace, membership and invitation business logic."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.security import hash_token
from models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    User,
    Workspace,
)
from repositories import (
    InvitationRepository,
    MembershipRepository,
    WorkspaceRepository,
)
from schemas import (
    InvitationCreate,
    InvitationCreatedResponse,
    InvitationResponse,
    MemberResponse,
    RoleUpdate,
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from services.exceptions import (
    AlreadyMemberError,
    InvitationEmailMismatchError,
    InvitationExpiredError,
    InvitationNotFoundError,
    InvitationUnavailableError,
    LastOwnerError,
    MemberNotFoundError,
    NotWorkspaceMemberError,
    OwnerRequiredError,
    WorkspaceNotFoundError,
    WorkspaceSlugAlreadyExistsError,
)


class WorkspaceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._workspaces = WorkspaceRepository(session)
        self._memberships = MembershipRepository(session)
        self._invitations = InvitationRepository(session)

    # ---------- workspaces ----------

    async def create(
        self, payload: WorkspaceCreate, creator: User
    ) -> WorkspaceResponse:
        if await self._workspaces.get_by_slug(payload.slug) is not None:
            raise WorkspaceSlugAlreadyExistsError()

        workspace = Workspace(
            name=payload.name, slug=payload.slug, created_by=creator.id
        )
        await self._workspaces.add(workspace)
        # The creator is always the first member and an owner.
        membership = Membership(
            user_id=creator.id,
            workspace_id=workspace.id,
            role=MembershipRole.OWNER,
        )
        await self._memberships.add(membership)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            # A concurrent create may have claimed the slug or (unlikely) the
            # unique member pair.
            raise WorkspaceSlugAlreadyExistsError() from exc
        return self._response(workspace, MembershipRole.OWNER)

    async def list_mine(self, user_id: uuid.UUID) -> list[WorkspaceResponse]:
        workspaces = await self._workspaces.list_for_user(user_id)
        roles = {
            membership.workspace_id: membership.role
            for membership in await self._memberships.list_for_user(user_id)
        }
        return [
            self._response(workspace, roles[workspace.id])
            for workspace in workspaces
            if workspace.id in roles
        ]

    async def get(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> WorkspaceResponse:
        membership = await self._require_membership(workspace_id, user_id)
        workspace = await self._workspaces.get_by_id(workspace_id)
        assert workspace is not None  # checked by _require_membership
        return self._response(workspace, membership.role)

    async def update(
        self, workspace_id: uuid.UUID, payload: WorkspaceUpdate, user_id: uuid.UUID
    ) -> WorkspaceResponse:
        await self._require_owner(workspace_id, user_id)
        workspace = await self._workspaces.get_by_id(workspace_id)
        assert workspace is not None  # checked by _require_owner

        changes = payload.model_dump(exclude_unset=True)
        if "slug" in changes and changes["slug"] is not None:
            existing = await self._workspaces.get_by_slug(changes["slug"])
            if existing is not None and existing.id != workspace_id:
                raise WorkspaceSlugAlreadyExistsError()
        for field, value in changes.items():
            if value is not None:
                setattr(workspace, field, value)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise WorkspaceSlugAlreadyExistsError() from exc
        # `updated_at` has an onupdate=func.now(), so it is expired after the
        # flush; refresh it through the async session before serializing.
        await self._session.refresh(workspace)
        return self._response(workspace, MembershipRole.OWNER)

    async def delete(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
        workspace = await self._require_owner(workspace_id, user_id)
        await self._workspaces.delete(workspace)
        await self._session.commit()

    # ---------- invitations ----------

    async def invite(
        self,
        workspace_id: uuid.UUID,
        payload: InvitationCreate,
        inviter_id: uuid.UUID,
    ) -> InvitationCreatedResponse:
        await self._require_inviter(workspace_id, inviter_id)
        if (
            await self._memberships.get_by_email_in_workspace(
                payload.email, workspace_id
            )
            is not None
        ):
            raise AlreadyMemberError()

        # Re-inviting replaces any outstanding invitation for this email.
        await self._invitations.revoke_pending(workspace_id, payload.email)
        token = secrets.token_urlsafe(32)
        invitation = Invitation(
            email=payload.email,
            workspace_id=workspace_id,
            role=payload.role,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC)
            + timedelta(days=get_settings().invitation_ttl_days),
        )
        await self._invitations.add(invitation)
        await self._session.commit()

        query = urlencode({"token": token})
        accept_url = f"{get_settings().invitation_accept_base_url}?{query}"
        return InvitationCreatedResponse(
            id=invitation.id,
            workspace_id=invitation.workspace_id,
            email=invitation.email,
            role=invitation.role,
            status=invitation.status,
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
            token=token,
            accept_url=accept_url,
        )

    async def list_invitations(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[InvitationResponse]:
        await self._require_membership(workspace_id, user_id)
        invitations = await self._invitations.list_for_workspace(workspace_id)
        return [InvitationResponse.model_validate(item) for item in invitations]

    async def accept(self, token: str, user: User) -> WorkspaceResponse:
        invitation = await self._invitations.get_by_token_hash(hash_token(token))
        if invitation is None:
            raise InvitationNotFoundError()

        expires_at = invitation.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            invitation.status = InvitationStatus.EXPIRED
            await self._session.commit()
            raise InvitationExpiredError()
        if invitation.status is not InvitationStatus.PENDING:
            raise InvitationUnavailableError()
        if invitation.email != user.email:
            raise InvitationEmailMismatchError()

        workspace = await self._workspaces.get_by_id(invitation.workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError()
        if await self._memberships.get(user.id, workspace.id) is not None:
            raise AlreadyMemberError()

        membership = Membership(
            user_id=user.id, workspace_id=workspace.id, role=invitation.role
        )
        await self._memberships.add(membership)
        invitation.status = InvitationStatus.ACCEPTED
        await self._session.commit()
        return self._response(workspace, invitation.role)

    # ---------- members ----------

    async def list_members(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[MemberResponse]:
        await self._require_membership(workspace_id, user_id)
        return await self._memberships.list_for_workspace(workspace_id)

    async def change_role(
        self,
        workspace_id: uuid.UUID,
        target_user_id: uuid.UUID,
        payload: RoleUpdate,
        user_id: uuid.UUID,
    ) -> MemberResponse:
        # Lock the workspace so concurrent owner changes cannot both pass the
        # last-owner check.
        await self._workspaces.get_by_id_for_update(workspace_id)
        await self._require_owner(workspace_id, user_id)
        target = await self._memberships.get(target_user_id, workspace_id)
        if target is None:
            raise MemberNotFoundError()

        if (
            target.role is MembershipRole.OWNER
            and payload.role is not MembershipRole.OWNER
            and await self._memberships.count_owners(workspace_id) <= 1
        ):
            raise LastOwnerError()
        target.role = payload.role
        await self._session.commit()

        user = await self._session.get(User, target_user_id)
        assert user is not None
        return MemberResponse(
            id=target.id,
            user_id=target.user_id,
            email=user.email,
            full_name=user.full_name,
            role=target.role,
            joined_at=target.created_at,
        )

    async def remove_member(
        self, workspace_id: uuid.UUID, target_user_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        await self._workspaces.get_by_id_for_update(workspace_id)
        await self._require_owner(workspace_id, user_id)
        target = await self._memberships.get(target_user_id, workspace_id)
        if target is None:
            raise MemberNotFoundError()

        if (
            target.role is MembershipRole.OWNER
            and await self._memberships.count_owners(workspace_id) <= 1
        ):
            raise LastOwnerError()
        await self._memberships.delete(target)
        await self._session.commit()

    # ---------- helpers ----------

    async def _require_membership(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> Membership:
        if await self._workspaces.get_by_id(workspace_id) is None:
            raise WorkspaceNotFoundError()
        membership = await self._memberships.get(user_id, workspace_id)
        if membership is None:
            raise NotWorkspaceMemberError()
        return membership

    async def _require_owner(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> Workspace:
        workspace = await self._workspaces.get_by_id(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError()
        membership = await self._memberships.get(user_id, workspace_id)
        if membership is None:
            raise NotWorkspaceMemberError()
        if membership.role is not MembershipRole.OWNER:
            raise OwnerRequiredError()
        return workspace

    async def _require_inviter(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        """Owners and admins can invite; plain members cannot."""
        membership = await self._require_membership(workspace_id, user_id)
        if membership.role not in (MembershipRole.OWNER, MembershipRole.ADMIN):
            raise OwnerRequiredError("Only owners and admins can invite members")

    @staticmethod
    def _response(workspace: Workspace, role: MembershipRole) -> WorkspaceResponse:
        # Built explicitly: `my_role` is request-specific and is not a column,
        # and Pydantic 2.14 removed `model_validate(update=...)`.
        return WorkspaceResponse(
            id=workspace.id,
            name=workspace.name,
            slug=workspace.slug,
            created_by=workspace.created_by,
            my_role=role,
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
        )
