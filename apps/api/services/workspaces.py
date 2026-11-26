"""Workspace, membership and invitation business logic.

Every method that touches workspace-scoped data goes through a repository
method that takes ``workspace_id`` and filters by it. Protected endpoints
receive a ``WorkspaceContext`` (resolved by ``get_workspace_context``) rather
than a bare user id, so membership and role are checked in one place.
"""

import secrets
import uuid
from dataclasses import dataclass
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
from services.audit import record as record_audit
from services.exceptions import (
    AlreadyMemberError,
    InvitationEmailMismatchError,
    InvitationExpiredError,
    InvitationNotFoundError,
    InvitationUnavailableError,
    LastOwnerError,
    MemberNotFoundError,
    NotWorkspaceMemberError,
    WorkspaceNotFoundError,
    WorkspaceSlugAlreadyExistsError,
)


@dataclass(frozen=True)
class WorkspaceContext:
    """The authenticated user, the workspace from the path, and their role."""

    user: User
    workspace: Workspace
    role: MembershipRole


class WorkspaceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._workspaces = WorkspaceRepository(session)
        self._memberships = MembershipRepository(session)
        self._invitations = InvitationRepository(session)

    # ---------- context ----------

    async def get_context(
        self, workspace_id: uuid.UUID, user: User
    ) -> WorkspaceContext:
        """Resolve a workspace path id into an authorized caller context."""
        workspace = await self._workspaces.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError()
        membership = await self._memberships.get(workspace_id, user.id)
        if membership is None:
            raise NotWorkspaceMemberError()
        return WorkspaceContext(user=user, workspace=workspace, role=membership.role)

    # ---------- workspaces ----------

    async def create(
        self, payload: WorkspaceCreate, creator: User
    ) -> WorkspaceResponse:
        if await self._workspaces.get_by_slug(payload.slug) is not None:
            raise WorkspaceSlugAlreadyExistsError()

        workspace_id = uuid.uuid4()
        workspace = Workspace(
            id=workspace_id,
            name=payload.name,
            slug=payload.slug,
            created_by=creator.id,
        )
        await self._workspaces.add(workspace, workspace_id)
        # The creator is always the first member and an owner.
        membership = Membership(
            user_id=creator.id,
            workspace_id=workspace_id,
            role=MembershipRole.OWNER,
        )
        await self._memberships.add(membership, workspace_id)
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

    def describe(self, context: WorkspaceContext) -> WorkspaceResponse:
        return self._response(context.workspace, context.role)

    async def update(
        self, context: WorkspaceContext, payload: WorkspaceUpdate
    ) -> WorkspaceResponse:
        workspace = context.workspace
        workspace_id = workspace.id
        changes = payload.model_dump(exclude_unset=True)
        if "slug" in changes and changes["slug"] is not None:
            existing = await self._workspaces.get_by_slug(
                changes["slug"], exclude_workspace_id=workspace_id
            )
            if existing is not None:
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
        return self._response(workspace, context.role)

    async def delete(self, context: WorkspaceContext) -> None:
        await record_audit(
            self._session,
            context.user,
            "workspace.deleted",
            workspace_id=context.workspace.id,
            target_type="workspace",
            target_id=context.workspace.id,
        )
        await self._workspaces.delete(context.workspace, context.workspace.id)
        await self._session.commit()

    # ---------- invitations ----------

    async def invite(
        self, context: WorkspaceContext, payload: InvitationCreate
    ) -> InvitationCreatedResponse:
        workspace_id = context.workspace.id
        if (
            await self._memberships.get_by_email_in_workspace(
                workspace_id, payload.email
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
        await self._invitations.add(invitation, workspace_id)
        await self._session.commit()

        query = urlencode({"token": token})
        accept_url = f"{get_settings().invitation_accept_base_url}?{query}"
        try:
            from services.invitations import InvitationEmailService

            await InvitationEmailService().send_invite(
                to_email=invitation.email,
                workspace_name=context.workspace.name,
                inviter_email=context.user.email,
                accept_url=accept_url,
            )
        except Exception:
            pass
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
        self, context: WorkspaceContext
    ) -> list[InvitationResponse]:
        invitations = await self._invitations.list_for_workspace(context.workspace.id)
        return [InvitationResponse.model_validate(item) for item in invitations]

    async def accept(self, token: str, user: User) -> WorkspaceResponse:
        # No workspace context yet: the caller is not a member until this
        # succeeds, so token lookup is deliberately global and then checked.
        invitation = await self._invitations.get_by_token_hash(hash_token(token))
        if invitation is None:
            raise InvitationNotFoundError()

        workspace_id = invitation.workspace_id
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

        workspace = await self._workspaces.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError()
        if await self._memberships.get(workspace_id, user.id) is not None:
            raise AlreadyMemberError()

        membership = Membership(
            user_id=user.id, workspace_id=workspace_id, role=invitation.role
        )
        await self._memberships.add(membership, workspace_id)
        invitation.status = InvitationStatus.ACCEPTED
        await self._session.commit()
        return self._response(workspace, invitation.role)

    # ---------- members ----------

    async def list_members(self, context: WorkspaceContext) -> list[MemberResponse]:
        return await self._memberships.list_for_workspace(context.workspace.id)

    async def change_role(
        self,
        context: WorkspaceContext,
        target_user_id: uuid.UUID,
        payload: RoleUpdate,
    ) -> MemberResponse:
        workspace_id = context.workspace.id
        # Lock the workspace so concurrent owner changes cannot both pass the
        # last-owner check.
        await self._workspaces.get_for_update(workspace_id)
        target = await self._memberships.get(workspace_id, target_user_id)
        if target is None:
            raise MemberNotFoundError()

        if (
            target.role is MembershipRole.OWNER
            and payload.role is not MembershipRole.OWNER
            and await self._memberships.count_owners(workspace_id) <= 1
        ):
            raise LastOwnerError()
        previous_role = target.role
        target.role = payload.role
        await record_audit(
            self._session,
            context.user,
            "member.role_changed",
            workspace_id=workspace_id,
            target_type="user",
            target_id=target_user_id,
            details={"from": str(previous_role), "to": str(payload.role)},
        )
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
        self, context: WorkspaceContext, target_user_id: uuid.UUID
    ) -> None:
        workspace_id = context.workspace.id
        await self._workspaces.get_for_update(workspace_id)
        target = await self._memberships.get(workspace_id, target_user_id)
        if target is None:
            raise MemberNotFoundError()

        if (
            target.role is MembershipRole.OWNER
            and await self._memberships.count_owners(workspace_id) <= 1
        ):
            raise LastOwnerError()
        await self._memberships.delete(target, workspace_id)
        await record_audit(
            self._session,
            context.user,
            "member.removed",
            workspace_id=workspace_id,
            target_type="user",
            target_id=target_user_id,
            details={"role": str(target.role)},
        )
        await self._session.commit()

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
