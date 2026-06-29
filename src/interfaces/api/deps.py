"""Request-scoped dependencies: container access and the authenticated principal.

Authentication accepts either a Bearer JWT (user sessions) or an `X-API-Key`
header (programmatic). Both resolve to a `Principal` carrying the tenant scope —
the tenant id is never read from the request body.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from src.config.container import Container, get_container
from src.domain.shared.identifiers import TenantId, UserId
from src.infrastructure.security.hashing import hash_api_key


@dataclass
class Principal:
    tenant_id: TenantId
    user_id: UserId | None
    role: str


def container_dep() -> Container:
    return get_container()


ContainerDep = Annotated[Container, Depends(container_dep)]


async def current_principal(
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> Principal:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        try:
            claims = container.tokens.decode(token)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
        if claims.get("type") != "access":
            raise HTTPException(status_code=401, detail="Wrong token type")
        return Principal(
            tenant_id=TenantId(uuid.UUID(claims["tenant_id"])),
            user_id=UserId(uuid.UUID(claims["sub"])),
            role=claims.get("role", "member"),
        )

    if x_api_key:
        async with container.unit_of_work() as uow:
            key = await uow.api_keys.get_by_hash(hash_api_key(x_api_key))
        if key is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return Principal(tenant_id=key.tenant_id, user_id=None, role="member")

    raise HTTPException(status_code=401, detail="Authentication required")


PrincipalDep = Annotated[Principal, Depends(current_principal)]
