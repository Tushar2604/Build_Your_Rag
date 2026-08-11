"""Creating a workspace — the part that is identical however you signed up.

Both sign-up paths (email + password, and Google) have to produce exactly the
same thing: a tenant, an owner, and a default assistant to talk to. Keeping that
in one place is what stops the two from drifting into subtly different accounts
— the kind of difference nobody notices until a Google-signup tenant is missing
its default assistant and every "getting started" flow dead-ends.
"""

from __future__ import annotations

import re
import secrets

from src.application.ports.repositories import UnitOfWork
from src.domain.chatbot.entities import Chatbot
from src.domain.tenant.entities import Role, Tenant, User
from src.domain.tenant.events import TenantProvisioned

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Slug suffix length for the auto-uniquifying path. Four hex chars is 65k
# variants per name — plenty, given it only runs when a slug already exists.
_SUFFIX_CHARS = 4


def slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")[:60] or "tenant"


def workspace_name_for(email: str, full_name: str = "") -> str:
    """A sensible workspace name when the person was never asked for one.

    Google sign-up has no "company name" field — inventing a prompt mid-flow
    would undo the point of one-click sign-in — so the name comes from what
    Google already told us, preferring their real name over their email local
    part.
    """
    stem = (full_name or "").strip() or (email or "").split("@")[0].replace(".", " ").strip()
    stem = stem[:100] or "My"
    return f"{stem.title()}'s Workspace"


async def unique_slug(uow: UnitOfWork, name: str) -> str:
    """A free slug for `name`, adding a short suffix only if it is taken.

    Used by the sign-up paths that cannot report a conflict back to a human —
    a Google sign-in must not fail because an unrelated tenant happens to share
    a workspace name.
    """
    base = slugify(name)
    if await uow.tenants.get_by_slug(base) is None:
        return base
    while True:
        candidate = f"{base[:55]}-{secrets.token_hex(_SUFFIX_CHARS // 2)}"
        if await uow.tenants.get_by_slug(candidate) is None:
            return candidate


async def provision_tenant(
    uow: UnitOfWork,
    *,
    tenant_name: str,
    owner_email: str,
    password_hash: str,
    slug: str,
) -> tuple[Tenant, User]:
    """Create the tenant, its owner, and a default assistant.

    The caller owns slug selection (strict for password sign-up, auto-uniquifying
    for SSO) and the commit, so this stays usable from both flows without
    guessing which failure mode the caller wants.
    """
    tenant = Tenant(name=tenant_name, slug=slug)
    uow.set_tenant_scope(tenant.id)
    await uow.tenants.add(tenant)

    user = User(
        email=owner_email,
        password_hash=password_hash,
        tenant_id=tenant.id,
        role=Role.OWNER,
    )
    await uow.users.add(user)
    await uow.flush()  # persist tenant before the chatbot FK check

    # Seed a ready-to-use default assistant so the tenant has something to talk
    # to the moment their first document finishes ingesting.
    await uow.chatbots.add(Chatbot(tenant_id=tenant.id, name="Default Assistant"))

    uow.collect_event(
        TenantProvisioned(
            tenant_id=tenant.id, tenant_name=tenant.name, owner_email=user.email
        )
    )
    return tenant, user
