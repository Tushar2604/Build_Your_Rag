"""Provision a new tenant with its owner user and a default chatbot."""

from __future__ import annotations

from src.application.dtos import AuthOutput, RegisterTenantInput
from src.application.ports.repositories import UnitOfWork
from src.application.ports.services import PasswordHasher, TokenService
from src.application.use_cases.provisioning import provision_tenant, slugify
from src.domain.shared.errors import ConflictError


class RegisterTenant:
    def __init__(self, uow: UnitOfWork, hasher: PasswordHasher, tokens: TokenService) -> None:
        self._uow = uow
        self._hasher = hasher
        self._tokens = tokens

    async def execute(self, data: RegisterTenantInput) -> AuthOutput:
        async with self._uow as uow:
            if await uow.users.get_by_email(data.owner_email):
                raise ConflictError("A user with this email already exists.")

            # Strict rather than auto-uniquifying: this caller *did* type a name,
            # so a clash is worth telling them about instead of silently handing
            # them "acme-3f9c". Google sign-up, which never asks for a name, uses
            # `unique_slug` instead.
            slug = slugify(data.tenant_name)
            if await uow.tenants.get_by_slug(slug):
                raise ConflictError("A tenant with a similar name already exists.")

            tenant, user = await provision_tenant(
                uow,
                tenant_name=data.tenant_name,
                owner_email=data.owner_email,
                password_hash=self._hasher.hash(data.password),
                slug=slug,
            )
            await uow.commit()

        pair = self._tokens.issue(
            user_id=str(user.id), tenant_id=str(tenant.id), role=user.role.value
        )
        return AuthOutput(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            tenant_id=tenant.id,
            user_id=user.id,
            role=user.role.value,
        )
