"""Unit tests for the tenant aggregate: Role, Tenant, User, ApiKey."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from src.domain.shared.identifiers import TenantId, new_id
from src.domain.tenant.entities import ApiKey, Role, Tenant, User


# --- Role ---
def test_role_values() -> None:
    assert Role.OWNER == "owner"
    assert Role.ADMIN == "admin"
    assert Role.MEMBER == "member"
    assert Role.VIEWER == "viewer"
    assert set(Role) == {Role.OWNER, Role.ADMIN, Role.MEMBER, Role.VIEWER}


# --- Tenant ---
def test_tenant_defaults() -> None:
    t = Tenant(name="Acme", slug="acme")
    # Raised in 0032: the booking agent is a multi-step tool loop, and at the
    # old 200k ceiling a workspace ran dry after about four bookings — then
    # every conversation on it failed until midnight.
    assert t.daily_token_quota == 2_000_000
    assert t.max_documents == 200
    assert t.is_active is True
    assert isinstance(t.id, uuid.UUID)
    assert isinstance(t.created_at, datetime)


def test_tenant_ids_are_unique() -> None:
    assert Tenant(name="a", slug="a").id != Tenant(name="b", slug="b").id


def test_tenant_deactivate() -> None:
    t = Tenant(name="Acme", slug="acme")
    t.deactivate()
    assert t.is_active is False


def test_tenant_overrides_apply() -> None:
    t = Tenant(name="Acme", slug="acme", daily_token_quota=10, max_documents=5)
    assert t.daily_token_quota == 10
    assert t.max_documents == 5


# --- User ---
def test_user_defaults() -> None:
    u = User(email="a@b.com", password_hash="h", tenant_id=TenantId(new_id()))
    assert u.role is Role.OWNER
    assert u.is_active is True
    assert isinstance(u.id, uuid.UUID)


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.OWNER, True),
        (Role.ADMIN, True),
        (Role.MEMBER, False),
        (Role.VIEWER, False),
    ],
)
def test_user_can_manage(role: Role, expected: bool) -> None:
    u = User(email="a@b.com", password_hash="h", tenant_id=TenantId(new_id()), role=role)
    assert u.can_manage() is expected


# --- ApiKey ---
def test_apikey_defaults() -> None:
    k = ApiKey(tenant_id=TenantId(new_id()), name="ci", key_hash="hash", prefix="rk_abc")
    assert k.is_active is True
    assert isinstance(k.id, uuid.UUID)
    assert k.prefix == "rk_abc"
    assert isinstance(k.created_at, datetime)
