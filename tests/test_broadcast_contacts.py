"""Unit tests for contact-list ingestion — the paste box operators actually use."""

from __future__ import annotations

from src.application.use_cases.broadcast import parse_contacts


def test_one_number_per_line() -> None:
    parsed = parse_contacts("+917502163963\n+971553752665\n")
    assert [p for p, _ in parsed.recipients] == ["+917502163963", "+971553752665"]
    assert parsed.invalid == []


def test_number_then_name() -> None:
    parsed = parse_contacts("+917502163963, Mohammed Yacoob\n+918143227567, Manikanta")
    assert parsed.recipients == [
        ("+917502163963", "Mohammed Yacoob"),
        ("+918143227567", "Manikanta"),
    ]


def test_name_then_number_column_order_does_not_matter() -> None:
    parsed = parse_contacts("Mohammed Yacoob, +917502163963")
    assert parsed.recipients == [("+917502163963", "Mohammed Yacoob")]


def test_csv_header_row_is_skipped_not_flagged_invalid() -> None:
    parsed = parse_contacts("name,phone\nManikanta,+918143227567")
    assert parsed.recipients == [("+918143227567", "Manikanta")]
    assert parsed.invalid == []


def test_unparseable_rows_are_reported_rather_than_dropped() -> None:
    # Silently discarding a contact is how a campaign quietly under-sends.
    parsed = parse_contacts("+917502163963\nnot a number\n555-1234")
    assert [p for p, _ in parsed.recipients] == ["+917502163963"]
    assert len(parsed.invalid) == 2


def test_duplicates_within_one_paste_collapse() -> None:
    parsed = parse_contacts("+917502163963\n+91 75021 63963\nwhatsapp:+917502163963")
    assert len(parsed.recipients) == 1


def test_blank_input_is_not_an_error() -> None:
    parsed = parse_contacts("   \n\n")
    assert parsed.recipients == [] and parsed.invalid == []


def test_extra_csv_columns_are_tolerated() -> None:
    parsed = parse_contacts("Manikanta,+918143227567,BIM Structure,3 years")
    phone, name = parsed.recipients[0]
    assert phone == "+918143227567"
    assert name == "Manikanta"
