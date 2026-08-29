"""Guard: one handset is one key.

The reported symptom was a contact showing up three times in Candidates with
the same name and the same number, each copy holding a different slice of the
conversation. `whatsapp_conversations` is unique on (owner, phone_number), and
four different writers were each supplying their own spelling of the number —
so "the same contact" was three different rows as far as the database was
concerned.
"""

from __future__ import annotations

import pytest
from src.domain.shared.phone import canonical_phone, phone_digits, same_phone


@pytest.mark.parametrize(
    "raw",
    [
        "+919220910108",
        "919220910108",
        "whatsapp:+919220910108",
        "+91 92209 10108",
        "+91-92209-10108",
        "919220910108@s.whatsapp.net",
        "919220910108:12@s.whatsapp.net",
        "(91) 92209 10108",
    ],
)
def test_every_shape_the_writers_produce_lands_on_one_key(raw: str) -> None:
    # This exact list is the bug: the live socket, the history import, the
    # Twilio webhook and a pasted campaign list each emit one of these.
    assert canonical_phone(raw) == "+919220910108"


def test_two_genuinely_different_numbers_stay_apart() -> None:
    assert canonical_phone("+919220910108") != canonical_phone("+919220910109")


def test_the_stored_form_is_the_one_the_bridge_already_emits() -> None:
    # Chosen so the backfill has almost nothing to do — most rows are already
    # correct, and a migration that rewrites every row is a migration that can
    # go wrong on more of them.
    assert canonical_phone("919220910108").startswith("+")


def test_something_that_was_never_a_number_is_left_alone() -> None:
    # Blanking it would orphan a thread somebody may still need to read; the
    # key just stops being a phone number.
    assert canonical_phone("unknown") == "unknown"
    assert canonical_phone("  spaced  ") == "spaced"


def test_a_digit_fragment_is_not_treated_as_a_phone_number() -> None:
    # Canonicalising a scrap would merge unrelated threads, which is worse than
    # leaving one odd key alone.
    assert phone_digits("12345") == ""
    assert phone_digits("1" * 20) == ""


def test_same_phone_compares_handsets_not_strings() -> None:
    assert same_phone("+971 50 123 4567", "971501234567")
    assert not same_phone("+971501234567", "+971501234568")


def test_two_equally_odd_keys_still_compare_equal() -> None:
    # The fallback matters: without it, every unparseable key would look
    # distinct from itself and re-create its thread on every message.
    assert same_phone("unknown", "unknown")
    assert not same_phone("unknown", "other")
