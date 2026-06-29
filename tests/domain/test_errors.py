"""Unit tests for the domain error hierarchy."""

from __future__ import annotations

import pytest
from src.domain.shared.errors import (
    ConflictError,
    DomainError,
    InvalidStateError,
    NotFoundError,
    PermissionDeniedError,
    QuotaExceededError,
)

_SUBCLASSES = [
    NotFoundError,
    ConflictError,
    PermissionDeniedError,
    QuotaExceededError,
    InvalidStateError,
]


def test_base_is_an_exception() -> None:
    assert issubclass(DomainError, Exception)


@pytest.mark.parametrize("err", _SUBCLASSES)
def test_every_domain_error_subclasses_base(err: type[DomainError]) -> None:
    assert issubclass(err, DomainError)


@pytest.mark.parametrize("err", _SUBCLASSES)
def test_can_raise_and_catch_as_base(err: type[DomainError]) -> None:
    with pytest.raises(DomainError):
        raise err("boom")


@pytest.mark.parametrize("err", _SUBCLASSES)
def test_message_is_preserved(err: type[DomainError]) -> None:
    assert str(err("specific message")) == "specific message"
