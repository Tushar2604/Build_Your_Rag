"""Domain-level errors.

These are framework-agnostic. The API layer maps them to HTTP status codes
(see `interfaces/api/errors.py`) so the domain never imports FastAPI.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain errors."""


class NotFoundError(DomainError):
    """An aggregate could not be found within the current tenant scope."""


class ConflictError(DomainError):
    """An operation violates a uniqueness or state invariant."""


class PermissionDeniedError(DomainError):
    """The actor is not allowed to perform this action."""


class QuotaExceededError(DomainError):
    """A tenant has exceeded a configured quota (tokens, documents, size)."""


class RateLimitedError(DomainError):
    """The caller exceeded a short-window request rate (burst guard)."""


class InvalidStateError(DomainError):
    """An operation is not valid for the entity's current lifecycle state."""


# What a customer is told when the workspace has run out of tokens for the day.
#
# Deliberately says nothing about quotas or tokens: the person on the other end
# is a patient or a client, and "daily token quota exceeded" is both meaningless
# to them and alarming. It also does not blame a glitch, because this is not
# one — it is a limit that will clear, and in the meantime a human has to pick
# the conversation up.
QUOTA_REPLY = (
    "Sorry, I can't reply right now — I've passed this to the team and "
    "someone will get back to you shortly."
)
