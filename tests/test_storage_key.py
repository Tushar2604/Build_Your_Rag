"""The storage key must never embed the raw filename (Windows MAX_PATH / R2 safety)."""

from __future__ import annotations

from src.application.use_cases.documents import _storage_ext


def test_keeps_simple_extension() -> None:
    assert _storage_ext("report.pdf") == ".pdf"
    assert _storage_ext("DATA.CSV") == ".csv"


def test_long_spacey_filename_yields_just_extension() -> None:
    name = "What Are Different Research Approaches, Types, and Limitations.pdf"
    assert _storage_ext(name) == ".pdf"


def test_no_or_weird_extension_is_dropped() -> None:
    assert _storage_ext("README") == ""
    assert _storage_ext("archive.tar.gz") == ".gz"
    assert _storage_ext("file.weird name") == ""  # space in suffix -> not alnum
    assert _storage_ext("a." ) == ""  # empty suffix
