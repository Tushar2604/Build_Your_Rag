"""Team management — the per-tenant "admin panel" entry point: an Owner/Admin
invites teammates with a role; the invitee accepts (token-scoped, no auth) to
create their own account under the SAME tenant. See `AdminPrincipalDep`
(`deps.py`) for the gate applied here and to every other admin-only router.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from src.application.use_cases.team import (
    AcceptInvite,
    GetInviteBootstrap,
    InviteTeammate,
    ListTeam,
)
from src.config.settings import get_settings
from src.domain.shared.errors import ConflictError, InvalidStateError, NotFoundError, PermissionDeniedError
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep
from src.interfaces.api.schemas import (
    AcceptInviteRequest,
    InviteBootstrapResponse,
    InviteTeammateRequest,
    TeamMemberResponse,
    TeamResponse,
    TenantInviteResponse,
    TokenResponse,
)

router = APIRouter(prefix="/team", tags=["team"])


def _invite_url(token: str) -> str:
    base = get_settings().public_frontend_base.rstrip("/")
    return f"{base}/accept-invite/{token}"


@router.get("", response_model=TeamResponse)
async def list_team(principal: AdminPrincipalDep, container: ContainerDep) -> TeamResponse:
    use_case = ListTeam(container.unit_of_work())
    users, invites = await use_case.execute(principal.tenant_id)
    return TeamResponse(
        members=[
            TeamMemberResponse(
                id=u.id, email=u.email, role=u.role.value, is_active=u.is_active,
                created_at=u.created_at,
            )
            for u in users
        ],
        pending_invites=[
            TenantInviteResponse(
                id=i.id, email=i.email, role=i.role, status=i.status,
                expires_at=i.expires_at, invite_url=_invite_url(i.token),
            )
            for i in invites
        ],
    )


@router.post("/invites", response_model=TenantInviteResponse, status_code=201)
async def invite_teammate(
    body: InviteTeammateRequest, principal: AdminPrincipalDep, container: ContainerDep
) -> TenantInviteResponse:
    settings = get_settings()
    use_case = InviteTeammate(container.unit_of_work(), container.email, settings.public_frontend_base)
    try:
        invite, email_sent = await use_case.execute(
            principal.tenant_id, inviter_role=principal.role, invitee_email=body.email, role=body.role,
        )
    except (ConflictError, InvalidStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return TenantInviteResponse(
        id=invite.id, email=invite.email, role=invite.role, status=invite.status,
        expires_at=invite.expires_at, invite_url=_invite_url(invite.token), email_sent=email_sent,
    )


# --- Public (token-scoped, no auth — the invitee has no account yet) ---


@router.get("/invites/{token}", response_model=InviteBootstrapResponse)
async def get_invite_bootstrap(token: str, container: ContainerDep) -> InviteBootstrapResponse:
    use_case = GetInviteBootstrap(container.unit_of_work())
    try:
        invite, tenant_name = await use_case.execute(token)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    valid = invite.status == "pending" and invite.expires_at > datetime.now(UTC)
    return InviteBootstrapResponse(
        tenant_name=tenant_name, email=invite.email, role=invite.role, valid=valid,
    )


@router.post("/invites/{token}/accept", response_model=TokenResponse)
async def accept_invite(
    token: str, body: AcceptInviteRequest, container: ContainerDep
) -> TokenResponse:
    use_case = AcceptInvite(container.unit_of_work(), container.hasher, container.tokens)
    try:
        result = await use_case.execute(token, body.password)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ConflictError, InvalidStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        tenant_id=result.tenant_id,
        user_id=result.user_id,
        role=result.role,
    )
