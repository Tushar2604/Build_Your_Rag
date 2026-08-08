"""A tenant's connection to a catalogue integration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.shared.identifiers import TenantId, new_id


@dataclass
class TenantIntegration:
    """Credentials + state for one integration, for one tenant.

    `config` holds only keys the integration's spec declares (see
    `validate_credentials`), and secret values are never returned to the browser
    — the API redacts them on the way out.
    """

    tenant_id: TenantId
    integration_id: str
    id: uuid.UUID = field(default_factory=new_id)
    config: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def replace_config(self, config: dict[str, str]) -> None:
        self.config = dict(config)
        self.updated_at = datetime.now(UTC)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.updated_at = datetime.now(UTC)

    def webhook_url(self) -> str:
        return self.config.get("webhook_url", "")
