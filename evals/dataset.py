"""Golden dataset: the labelled cases an eval run scores against.

A case pairs a question with (a) the document/chunk ids that *should* be
retrieved to answer it, and (b) optional notes on the expected answer. We keep
the schema small and JSONL-backed so non-engineers (the people who own a corpus)
can add cases by appending a line, and so cases version cleanly in git.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EvalCase:
    """One labelled question.

    `relevant_doc_ids` is the ground truth for retrieval metrics. `expected_*`
    fields feed the generation judge and the deterministic refusal check; both
    are optional so a corpus owner can contribute retrieval-only cases.
    """

    id: str
    question: str
    relevant_doc_ids: list[str] = field(default_factory=list)
    expected_answer: str | None = None
    # True for adversarial / out-of-scope questions the bot should refuse.
    expect_refusal: bool = False
    # Free-form tags for slicing a report (e.g. "finance", "multi-hop").
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> EvalCase:
        if "id" not in raw or "question" not in raw:
            raise ValueError(f"Eval case missing required 'id'/'question': {raw!r}")
        return cls(
            id=str(raw["id"]),
            question=str(raw["question"]),
            relevant_doc_ids=[str(d) for d in raw.get("relevant_doc_ids", [])],
            expected_answer=raw.get("expected_answer"),
            expect_refusal=bool(raw.get("expect_refusal", False)),
            tags=[str(t) for t in raw.get("tags", [])],
        )


@dataclass(frozen=True)
class GoldenDataset:
    name: str
    cases: list[EvalCase]

    def __len__(self) -> int:
        return len(self.cases)

    def __iter__(self) -> Iterator[EvalCase]:
        return iter(self.cases)

    @classmethod
    def load_jsonl(cls, path: str | Path) -> GoldenDataset:
        """Load a `.jsonl` file — one JSON object per line, blank lines skipped.

        Line-delimited (not a JSON array) so a single malformed case is easy to
        locate and append-only edits never touch existing lines.
        """
        p = Path(path)
        cases: list[EvalCase] = []
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                cases.append(EvalCase.from_dict(json.loads(line)))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{p}:{lineno}: invalid eval case — {exc}") from exc
        if not cases:
            raise ValueError(f"{p}: dataset is empty")
        ids = [c.id for c in cases]
        if len(set(ids)) != len(ids):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"{p}: duplicate case ids: {dupes}")
        return cls(name=p.stem, cases=cases)
