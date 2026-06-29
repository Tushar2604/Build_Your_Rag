"""Tenant & user aggregates.

A Tenant is the unit of isolation: every document, chatbot, and chat belongs to
exactly one tenant. A User authenticates and belongs to a tenant via a role.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from src.domain.shared.identifiers import TenantId, UserId, new_id


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


@dataclass
class Tenant:
    name: str
    slug: str
    id: TenantId = field(default_factory=lambda: TenantId(new_id()))
    daily_token_quota: int = 200_000
    max_documents: int = 200
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def deactivate(self) -> None:
        self.is_active = False


@dataclass
class User:
    email: str
    password_hash: str
    tenant_id: TenantId
    role: Role = Role.OWNER
    id: UserId = field(default_factory=lambda: UserId(new_id()))
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def can_manage(self) -> bool:
        return self.role in (Role.OWNER, Role.ADMIN)


@dataclass
class ApiKey:
    """A programmatic key scoped to a tenant. We store only the hash."""

    tenant_id: TenantId
    name: str
    key_hash: str
    prefix: str  # first chars, shown in UI to identify the key
    id: uuid.UUID = field(default_factory=new_id)
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
