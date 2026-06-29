"""Report types: per-case results and the aggregate scorecard.

An `EvalReport` is the serialisable artifact of a run. It is what gets written as
a baseline, diffed by the regression gate, and printed in CI. Keeping it a plain
dataclass with `to_dict`/`from_dict` means baselines are human-readable JSON that
review cleanly in a PR.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class CaseResult:
    case_id: str
    question: str
    metrics: dict[str, float]
    answer: str = ""
    tags: list[str] = field(default_factory=list)
    judge_ok: bool = True  # False if an LLM-judge axis errored for this case

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvalReport:
    dataset: str
    num_cases: int
    aggregate: dict[str, float]  # mean of each metric across cases
    cases: list[CaseResult] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    target: str = "unknown"

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "target": self.target,
            "num_cases": self.num_cases,
            "created_at": self.created_at,
            "aggregate": self.aggregate,
            "cases": [c.to_dict() for c in self.cases],
        }

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> EvalReport:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            dataset=data["dataset"],
            num_cases=data["num_cases"],
            aggregate=data["aggregate"],
            cases=[
                CaseResult(
                    case_id=c["case_id"],
                    question=c.get("question", ""),
                    metrics=c["metrics"],
                    answer=c.get("answer", ""),
                    tags=c.get("tags", []),
                    judge_ok=c.get("judge_ok", True),
                )
                for c in data.get("cases", [])
            ],
            created_at=data.get("created_at", ""),
            target=data.get("target", "unknown"),
        )

    def summary_table(self) -> str:
        """A compact, terminal-friendly aggregate scorecard."""
        width = max((len(k) for k in self.aggregate), default=6)
        lines = [f"  {k.ljust(width)}  {v:6.3f}" for k, v in sorted(self.aggregate.items())]
        header = f"Eval report — {self.dataset} via {self.target} ({self.num_cases} cases)"
        return header + "\n" + "\n".join(lines)
