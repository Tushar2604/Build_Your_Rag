"""Auth endpoints: register a tenant, log in."""

from __future__ import annotations

from fastapi import APIRouter

from src.application.dtos import RegisterTenantInput
from src.application.use_cases.authenticate import AuthenticateUser, LoginInput
from src.application.use_cases.register_tenant import RegisterTenant
from src.interfaces.api.deps import ContainerDep
from src.interfaces.api.schemas import (
    AuthProvidersResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/providers", response_model=AuthProvidersResponse)
async def providers(container: ContainerDep) -> AuthProvidersResponse:
    """Which sign-in methods this deployment actually offers.

    Served so the login page can hide a Google button that would only fail —
    a visible button that 400s is worse than no button, and the SPA has no
    other way to know whether the server has an OAuth app registered.
    """
    client = container.oauth.get("google_login")
    return AuthProvidersResponse(google=bool(client and client.enabled))


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, container: ContainerDep) -> TokenResponse:
    use_case = RegisterTenant(container.unit_of_work(), container.hasher, container.tokens)
    result = await use_case.execute(
        RegisterTenantInput(
            tenant_name=body.tenant_name, owner_email=body.email, password=body.password
        )
    )
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        tenant_id=result.tenant_id,
        user_id=result.user_id,
        role=result.role,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, container: ContainerDep) -> TokenResponse:
    use_case = AuthenticateUser(container.unit_of_work(), container.hasher, container.tokens)
    result = await use_case.execute(LoginInput(email=body.email, password=body.password))
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        tenant_id=result.tenant_id,
        user_id=result.user_id,
        role=result.role,
    )
