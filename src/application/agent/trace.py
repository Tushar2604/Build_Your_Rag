"""Structured trace of an agent run — the observability primitive.

Every think/act/observe step is recorded so a run can be replayed, debugged, and
scored. "Read an agent trace log" is a first-class workflow here: the trace is
returned with the answer, persisted via the request log, and is exactly what an
eval target or a Langfuse/OpenTelemetry exporter would walk.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentStep:
    index: int
    thought: str
    action: str  # tool name, or "final"
    action_input: dict
    observation: str = ""
    model: str = ""  # which model tier served this step (from the router)
    # Structured payload the tool returned (e.g. citations) — kept off the
    # observation string so the use case recovers it without re-parsing text.
    data: dict = field(default_factory=dict)


@dataclass
class AgentTrace:
    question: str
    steps: list[AgentStep] = field(default_factory=list)
    final_answer: str = ""
    stop_reason: str = ""  # "final" | "max_steps" | "error"
    tokens_used: int = 0
    provider: str | None = None

    def add(self, step: AgentStep) -> None:
        self.steps.append(step)

    @property
    def num_steps(self) -> int:
        return len(self.steps)

    def tools_used(self) -> list[str]:
        return [s.action for s in self.steps if s.action != "final"]

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "final_answer": self.final_answer,
            "stop_reason": self.stop_reason,
            "tokens_used": self.tokens_used,
            "provider": self.provider,
            "num_steps": self.num_steps,
            "tools_used": self.tools_used(),
            "steps": [
                {
                    "index": s.index,
                    "thought": s.thought,
                    "action": s.action,
                    "action_input": s.action_input,
                    "observation": s.observation[:500],
                    "model": s.model,
                }
                for s in self.steps
            ],
        }
