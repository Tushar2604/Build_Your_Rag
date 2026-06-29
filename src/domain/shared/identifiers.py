"""Strongly-typed identifiers.

We use UUIDs everywhere (generated app-side) so entities can be created without
a database round-trip, and so IDs are non-guessable across tenants.
"""

from __future__ import annotations

import uuid
from typing import NewType

TenantId = NewType("TenantId", uuid.UUID)
UserId = NewType("UserId", uuid.UUID)
DocumentId = NewType("DocumentId", uuid.UUID)
ChatbotId = NewType("ChatbotId", uuid.UUID)
SessionId = NewType("SessionId", uuid.UUID)
MessageId = NewType("MessageId", uuid.UUID)


def new_id() -> uuid.UUID:
    return uuid.uuid4()
