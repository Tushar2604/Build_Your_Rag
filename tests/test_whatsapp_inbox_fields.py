"""The pure rules behind the shared-inbox fields the PATCH endpoint writes.

Tags arrive from a free-text chip input and the status column is a varchar the
API promises as one of two values — both are places where the database will
happily accept something the UI then renders wrongly, and neither is worth a
round trip to prove.
"""

from __future__ import annotations

from src.interfaces.api.routers.whatsapp_web import _clean_tags, _thread_status


def test_tags_are_trimmed() -> None:
    assert _clean_tags(["  Hot Lead  "]) == ["Hot Lead"]


def test_a_tag_typed_twice_with_different_spacing_lands_once() -> None:
    # The realistic failure: two chips that look identical and filter
    # differently, because one of them has a trailing space.
    assert _clean_tags(["Hot Lead", "Hot Lead "]) == ["Hot Lead"]


def test_duplicates_are_matched_ignoring_case() -> None:
    assert _clean_tags(["Hot Lead", "hot lead"]) == ["Hot Lead"]


def test_the_order_they_were_typed_in_is_kept() -> None:
    # Tags read as a sequence someone built up, not a set — sorting them would
    # shuffle the row every time one was added.
    assert _clean_tags(["Proposal Sent", "Hot Lead", "UAE"]) == [
        "Proposal Sent",
        "Hot Lead",
        "UAE",
    ]


def test_blank_tags_are_dropped() -> None:
    assert _clean_tags(["", "   ", "Real"]) == ["Real"]


def test_an_over_long_tag_is_cut_rather_than_rejected() -> None:
    # Losing the whole edit because one chip ran long is worse than trimming
    # it; the column is bounded either way.
    assert _clean_tags(["x" * 90]) == ["x" * 40]


def test_status_narrows_to_the_two_values_the_api_promises() -> None:
    assert _thread_status("open") == "open"
    assert _thread_status("closed") == "closed"


def test_an_unexpected_status_reads_as_open() -> None:
    # The column is a varchar so the set can grow later. Until it does,
    # anything unrecognised has to render as something — and a thread that
    # silently disappears from the default view is the worse failure.
    assert _thread_status("snoozed") == "open"
    assert _thread_status("") == "open"
