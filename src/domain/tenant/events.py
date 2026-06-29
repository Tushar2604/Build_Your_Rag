from __future__ import annotations

from dataclasses import dataclass

from src.domain.shared.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class TenantProvisioned(DomainEvent):
    # NB: not `name` — that would shadow the inherited DomainEvent.name property
    # (which has no setter) and make the event impossible to construct.
    tenant_name: str
    owner_email: str


@dataclass(frozen=True, kw_only=True)
class QuotaExceeded(DomainEvent):
    quota_kind: str  # "tokens" | "documents" | "upload_size"
    limit: int
