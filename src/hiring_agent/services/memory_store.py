"""HiringMemoryStore — high-level persistent memory for a hiring-agent run.

Wraps the repository with run-lifecycle operations and records into the five
memory buckets the task calls for:

    completed_steps      — each workflow transition that finished
    tool_outputs         — every tool's observation + structured payload
    llm_reasoning        — reasoning/explanations surfaced by tools or the LLM
    conversation         — the running assistant/system message trail
    candidate_decisions  — decisions taken at decision states (schedule, email,
                           feedback, shortlist)

Persisting after every step is what makes a run resumable: an interruption
leaves the row at its last completed state with status RUNNING (found by
`find_resumable`), and `WorkflowEngine.resume` continues from there.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from src.hiring_agent.persistence.repository import HiringMemoryRepository
from src.hiring_agent.types.memory import HiringAgentMemory, HiringMemoryStatus

# Workflow states whose tool output represents a candidate decision worth
# recording distinctly.
_DECISION_STATES = {"SCHEDULE", "EMAIL", "COLLECT_FEEDBACK", "SHORTLIST"}
# Keys in a tool's `data` payload that carry reasoning/explanations.
_REASONING_KEYS = ("reasoning", "explanation", "extraction_note", "note")


class HiringMemoryStore:
    def __init__(self, repository: HiringMemoryRepository | None = None) -> None:
        self._repo = repository or HiringMemoryRepository()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_run(
        self, tenant_id: uuid.UUID, current_state: str
    ) -> HiringAgentMemory:
        memory = HiringAgentMemory(
            tenant_id=tenant_id,
            status=HiringMemoryStatus.RUNNING,
            current_state=str(current_state),
        )
        await self._repo.save(memory)
        return memory

    async def start_execution(
        self, tenant_id: uuid.UUID, cursor: object, current_state: str
    ) -> HiringAgentMemory:
        """Create a run pre-loaded with executor state (plan/cursor)."""
        memory = HiringAgentMemory(
            tenant_id=tenant_id,
            status=HiringMemoryStatus.RUNNING,
            current_state=current_state,
            execution=cursor,  # ExecutionCursor
        )
        await self._repo.save(memory)
        return memory

    async def persist(self, memory: HiringAgentMemory) -> None:
        """Persist the current memory (including executor cursor/status)."""
        await self._touch(memory)

    async def complete(self, memory: HiringAgentMemory) -> None:
        memory.status = HiringMemoryStatus.COMPLETED
        memory.current_state = "COMPLETE"
        await self._touch(memory)

    async def interrupt(
        self, memory: HiringAgentMemory, error: str | None = None
    ) -> None:
        memory.status = HiringMemoryStatus.INTERRUPTED
        if error:
            memory.error = error[:500]
        await self._touch(memory)

    async def fail(self, memory: HiringAgentMemory, error: str) -> None:
        memory.status = HiringMemoryStatus.FAILED
        memory.error = error[:500]
        await self._touch(memory)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def record_step(
        self,
        memory: HiringAgentMemory,
        *,
        step: int,
        from_state: str,
        to_state: str,
        tool_name: str | None,
        observation: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Record one finished workflow step across all relevant buckets."""
        data = data or {}
        ts = datetime.now(UTC).isoformat()

        memory.completed_steps.append(
            {
                "step": step,
                "from_state": str(from_state),
                "to_state": str(to_state),
                "tool": tool_name,
                "timestamp": ts,
            }
        )
        memory.tool_outputs.append(
            {"step": step, "tool": tool_name, "observation": observation, "data": data}
        )
        memory.conversation.append(
            {"role": "assistant", "state": str(from_state), "content": observation}
        )

        reasoning = self._extract_reasoning(data)
        if reasoning:
            memory.llm_reasoning.append(
                {"step": step, "state": str(from_state), "reasoning": reasoning}
            )

        if str(from_state) in _DECISION_STATES:
            memory.candidate_decisions.append(
                {
                    "step": step,
                    "state": str(from_state),
                    "tool": tool_name,
                    "summary": observation,
                }
            )

        memory.current_state = str(to_state)
        await self._touch(memory)

    async def record_reasoning(
        self, memory: HiringAgentMemory, reasoning: str, *, state: str = ""
    ) -> None:
        memory.llm_reasoning.append({"state": state, "reasoning": reasoning})
        await self._touch(memory)

    async def record_message(
        self, memory: HiringAgentMemory, role: str, content: str
    ) -> None:
        memory.conversation.append({"role": role, "content": content})
        await self._touch(memory)

    async def record_decision(
        self, memory: HiringAgentMemory, decision: dict
    ) -> None:
        memory.candidate_decisions.append(decision)
        await self._touch(memory)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID
    ) -> HiringAgentMemory | None:
        return await self._repo.get(tenant_id, run_id)

    async def find_resumable(
        self, tenant_id: uuid.UUID | None = None
    ) -> list[HiringAgentMemory]:
        return await self._repo.find_resumable(tenant_id)

    async def list_runs(
        self, tenant_id: uuid.UUID, limit: int = 50
    ) -> list[HiringAgentMemory]:
        return await self._repo.list_for_tenant(tenant_id, limit)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _touch(self, memory: HiringAgentMemory) -> None:
        memory.updated_at = datetime.now(UTC)
        await self._repo.save(memory)

    @staticmethod
    def _extract_reasoning(data: dict[str, Any]) -> str | None:
        for key in _REASONING_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
        # Ranking output: collect the per-candidate explanations.
        ranked = data.get("ranked")
        if isinstance(ranked, list):
            notes = [
                r["explanation"]
                for r in ranked
                if isinstance(r, dict) and r.get("explanation")
            ]
            if notes:
                return " | ".join(notes[:5])
        return None
