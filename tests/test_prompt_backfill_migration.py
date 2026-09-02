"""Guard: the newest backfill migration's frozen copy of the stock prompt must
match the domain.

Each prompt-wording change ships two things together: an edit to
`_DEFAULT_SECTIONS`, and a migration that backfills existing assistants still
running the *previous* stock wording (matched by SHA-256, so an operator's own
edits are never touched — see 0014 and 0030's own docstrings for why the
section bodies are frozen inline rather than imported from `src.domain`).

The cost of freezing is drift: edit `_DEFAULT_SECTIONS` without a new migration
and newly created assistants end up with different wording from freshly
migrated ones. This test makes that drift fail immediately by comparing the
domain constant against whichever migration is currently the newest. If it
fires because you just changed the stock prompt, the fix is a new migration —
freeze the new sections in it, and repoint `MIGRATION`/`_MODULE_NAME` below at
it, the same way this file moved from 0014 to 0030.
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

_MODULE_NAME = "m0030"
MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "0030_flow_asks_name_first.py"
)


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_frozen_sections_match_the_domain_sections(migration) -> None:
    frozen = [(t, b) for t, b in migration._NEW_SECTIONS]
    live = [(s.title, s.body) for s in default_flow_sections()]
    assert frozen == live, (
        "migration 0030 has drifted from _DEFAULT_SECTIONS — add a new migration "
        "rather than editing 0030"
    )


def test_frozen_compose_matches_the_domain_compose(migration) -> None:
    assert migration._compose(migration._NEW_SECTIONS) == DEFAULT_SYSTEM_PROMPT
    assert migration._compose(migration._NEW_SECTIONS) == compose_system_prompt(
        default_flow_sections()
    )


def test_current_default_is_not_treated_as_stale(migration) -> None:
    # The digest names the prompt to REPLACE. If the current default's own
    # digest ever matched it, the migration would rewrite assistants that are
    # already correct on every future run.
    digest = hashlib.sha256(DEFAULT_SYSTEM_PROMPT.encode()).hexdigest()
    assert digest != migration._STOCK_DIGEST


def test_empty_prompt_is_not_matched_as_stock(migration) -> None:
    # Defensive: a NULL/empty system_prompt must not hash into the replace set.
    assert hashlib.sha256(b"").hexdigest() != migration._STOCK_DIGEST
