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
InterviewId = NewType("InterviewId", uuid.UUID)
InterviewBatchId = NewType("InterviewBatchId", uuid.UUID)
BatchCandidateId = NewType("BatchCandidateId", uuid.UUID)

# Scheduling. Separate ids rather than one generic "entity id" so a
# resource can never be passed where a service is expected.
LocationId = NewType("LocationId", uuid.UUID)
ServiceId = NewType("ServiceId", uuid.UUID)
ResourceId = NewType("ResourceId", uuid.UUID)
AppointmentId = NewType("AppointmentId", uuid.UUID)
ReservationId = NewType("ReservationId", uuid.UUID)
AvailabilityRuleId = NewType("AvailabilityRuleId", uuid.UUID)
BlockedPeriodId = NewType("BlockedPeriodId", uuid.UUID)


def new_id() -> uuid.UUID:
    return uuid.uuid4()
