"""Provision a new tenant with its owner user and a default chatbot."""

from __future__ import annotations

import re

from src.application.dtos import AuthOutput, RegisterTenantInput
from src.application.ports.repositories import UnitOfWork
from src.application.ports.services import PasswordHasher, TokenService
from src.domain.chatbot.entities import Chatbot
from src.domain.shared.errors import ConflictError
from src.domain.tenant.entities import Role, Tenant, User
from src.domain.tenant.events import TenantProvisioned

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")[:60] or "tenant"


class RegisterTenant:
    def __init__(self, uow: UnitOfWork, hasher: PasswordHasher, tokens: TokenService) -> None:
        self._uow = uow
        self._hasher = hasher
        self._tokens = tokens

    async def execute(self, data: RegisterTenantInput) -> AuthOutput:
        async with self._uow as uow:
            if await uow.users.get_by_email(data.owner_email):
                raise ConflictError("A user with this email already exists.")

            slug = _slugify(data.tenant_name)
            if await uow.tenants.get_by_slug(slug):
                raise ConflictError("A tenant with a similar name already exists.")

            tenant = Tenant(name=data.tenant_name, slug=slug)
            uow.set_tenant_scope(tenant.id)
            await uow.tenants.add(tenant)

            user = User(
                email=data.owner_email,
                password_hash=self._hasher.hash(data.password),
                tenant_id=tenant.id,
                role=Role.OWNER,
            )
            await uow.users.add(user)
            await uow.flush()  # persist tenant before chatbot FK check

            # Seed a ready-to-use default chatbot so the tenant has something to
            # talk to the moment their first document finishes ingesting.
            await uow.chatbots.add(Chatbot(tenant_id=tenant.id, name="Default Assistant"))

            uow.collect_event(
                TenantProvisioned(
                    tenant_id=tenant.id, tenant_name=tenant.name, owner_email=user.email
                )
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
        )
