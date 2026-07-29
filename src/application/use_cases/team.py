"""Team management: an Owner/Admin invites a teammate into their EXISTING
tenant with a chosen role, and the teammate accepts the invite to create
their own account — the per-tenant "admin panel" signup path, distinct from
`RegisterTenant` (which always provisions a brand-new tenant + chatbot).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from src.application.dtos import AuthOutput
from src.application.ports.repositories import TenantInvite, UnitOfWork
from src.application.ports.services import PasswordHasher, TokenService
from src.domain.shared.errors import (
    ConflictError,
    InvalidStateError,
    NotFoundError,
    PermissionDeniedError,
)
from src.domain.shared.identifiers import TenantId
from src.domain.tenant.entities import Role, User
from src.infrastructure.email.resend import ResendEmailSender

log = structlog.get_logger(__name__)

_INVITE_VALID_DAYS = 7
_INVITABLE_ROLES = {Role.ADMIN.value, Role.MEMBER.value, Role.VIEWER.value}


class InviteTeammate:
    def __init__(
        self, uow: UnitOfWork, email: ResendEmailSender, frontend_base_url: str
    ) -> None:
        self._uow = uow
        self._email = email
        self._frontend_base = frontend_base_url.rstrip("/")

    async def execute(
        self, tenant_id: TenantId, *, inviter_role: str, invitee_email: str, role: str
    ) -> tuple[TenantInvite, bool]:
        """Returns (invite, email_sent). The invite link is always returned to
        the caller regardless of email_sent, so the admin can copy/share it
        manually — same fallback pattern as interview invites and WhatsApp
        channel connect."""
        if inviter_role not in (Role.OWNER.value, Role.ADMIN.value):
            raise PermissionDeniedError("Only an owner or admin can invite teammates.")
        if role not in _INVITABLE_ROLES:
            raise InvalidStateError(f"Invalid role: {role!r}")

        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            if await uow.users.get_by_email(invitee_email):
                raise ConflictError("A user with this email already exists.")
            tenant = await uow.tenants.get(tenant_id)
            if tenant is None:
                raise NotFoundError("Tenant not found.")

            invite = TenantInvite(
                tenant_id=tenant_id,
                email=invitee_email,
                role=role,
                expires_at=datetime.now(UTC) + timedelta(days=_INVITE_VALID_DAYS),
            )
            await uow.tenant_invites.add(invite)
            await uow.commit()

        invite_url = f"{self._frontend_base}/accept-invite/{invite.token}"
        email_sent = await self._try_send_invite(tenant.name, invitee_email, invite_url)
        return invite, email_sent

    async def _try_send_invite(self, tenant_name: str, to: str, invite_url: str) -> bool:
        if not self._email.enabled:
            return False
        try:
            return await self._email.send(
                to=to,
                subject=f"You've been invited to join {tenant_name}",
                html=(
                    f"<p>You've been invited to join <strong>{tenant_name}</strong>.</p>"
                    f"<p>Set up your account here: "
                    f"<a href=\"{invite_url}\">{invite_url}</a></p>"
                ),
            )
        except Exception:  # noqa: BLE001 - email is best-effort, the link is always returned too
            log.warning("team.invite_email_failed", to=to)
            return False


class GetInviteBootstrap:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, token: str) -> tuple[TenantInvite, str]:
        """Returns (invite, tenant_name) for the accept-invite page."""
        async with self._uow as uow:
            invite = await uow.tenant_invites.get_by_token(token)
            if invite is None:
                raise NotFoundError("Invite not found.")
            tenant = await uow.tenants.get(invite.tenant_id)
        return invite, tenant.name if tenant else ""


class AcceptInvite:
    def __init__(self, uow: UnitOfWork, hasher: PasswordHasher, tokens: TokenService) -> None:
        self._uow = uow
        self._hasher = hasher
        self._tokens = tokens

    async def execute(self, token: str, password: str) -> AuthOutput:
        async with self._uow as uow:
            invite = await uow.tenant_invites.get_by_token(token)
            if invite is None:
                raise NotFoundError("Invite not found.")
            if invite.status != "pending":
                raise InvalidStateError("This invite has already been used.")
            if invite.expires_at < datetime.now(UTC):
                raise InvalidStateError("This invite has expired.")
            if await uow.users.get_by_email(invite.email):
                raise ConflictError("A user with this email already exists.")

            uow.set_tenant_scope(invite.tenant_id)
            user = User(
                email=invite.email,
                password_hash=self._hasher.hash(password),
                tenant_id=invite.tenant_id,
                role=Role(invite.role),
            )
            await uow.users.add(user)
            await uow.tenant_invites.mark_accepted(invite)
            await uow.commit()

        pair = self._tokens.issue(
            user_id=str(user.id), tenant_id=str(user.tenant_id), role=user.role.value
        )
        return AuthOutput(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            tenant_id=user.tenant_id,
            user_id=user.id,
            role=user.role.value,
        )


class ListTeam:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, tenant_id: TenantId) -> tuple[list[User], list[TenantInvite]]:
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            users = await uow.users.list_for_tenant(tenant_id)
            invites = await uow.tenant_invites.list_for_tenant(tenant_id)
        pending = [i for i in invites if i.status == "pending"]
        return users, pending
