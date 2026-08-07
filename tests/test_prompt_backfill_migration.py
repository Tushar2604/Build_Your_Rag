"""Guard: migration 0014's frozen copy of the stock prompt must match the domain.

0014 backfills existing assistants with a copy of the section bodies inlined at
the time it was written (deliberately — a migration that imports live domain
constants stops being reproducible the moment those constants change).

The cost of freezing is drift: edit `_DEFAULT_SECTIONS` and migrated assistants
silently end up with different wording from newly created ones. This test makes
that drift fail immediately. If it fires, the fix is a NEW migration, not an
edit to 0014.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest
from src.domain.chatbot.entities import (
    DEFAULT_SYSTEM_PROMPT,
    compose_system_prompt,
    default_flow_sections,
)

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "0014_tighten_default_prompt.py"
)


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("m0014", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_frozen_sections_match_the_domain_sections(migration) -> None:
    frozen = [(t, b) for t, b in migration._NEW_SECTIONS]
    live = [(s.title, s.body) for s in default_flow_sections()]
    assert frozen == live, (
        "migration 0014 has drifted from _DEFAULT_SECTIONS — add a new migration "
        "rather than editing 0014"
    )


def test_frozen_compose_matches_the_domain_compose(migration) -> None:
    assert migration._compose(migration._NEW_SECTIONS) == DEFAULT_SYSTEM_PROMPT
    assert migration._compose(migration._NEW_SECTIONS) == compose_system_prompt(
        default_flow_sections()
    )


def test_current_default_is_not_treated_as_stale(migration) -> None:
    # The digest set names prompts to REPLACE. If the current default ever lands
    # in it, the migration would rewrite assistants that are already correct.
    digest = hashlib.sha256(DEFAULT_SYSTEM_PROMPT.encode()).hexdigest()
    assert digest not in migration._STOCK_DIGESTS


def test_stale_digests_are_recorded_for_both_shipped_defaults(migration) -> None:
    # One per prompt this project has shipped: the original single blob, and the
    # same text recomposed as sections. Losing either strands those assistants.
    assert len(migration._STOCK_DIGESTS) == 2


def test_empty_prompt_is_not_matched_as_stock(migration) -> None:
    # Defensive: a NULL/empty system_prompt must not hash into the replace set.
    assert hashlib.sha256(b"").hexdigest() not in migration._STOCK_DIGESTS
