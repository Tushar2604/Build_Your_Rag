"""Repository for hiring-agent persistent memory.

Reuses the shared async sessionmaker (the same engine the rest of the app uses).
Every query is tenant-scoped by an explicit `tenant_id` filter — the active
isolation guard the codebase relies on (Postgres RLS is a dormant backstop).
Upserts are idempotent so a run can be persisted repeatedly (once per step).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.hiring_agent.persistence.models import HiringAgentMemoryModel
from src.hiring_agent.types.memory import HiringAgentMemory, HiringMemoryStatus

# Non-terminal states that may be resumed after an interruption.
_RESUMABLE = (HiringMemoryStatus.RUNNING.value, HiringMemoryStatus.INTERRUPTED.value)


class HiringMemoryRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession] | None = None) -> None:
        # Deferred: resolve the shared sessionmaker on first use so importing
        # this module never forces the DB engine to be built.
        self._sessionmaker = sessionmaker

    def _sm(self) -> async_sessionmaker[AsyncSession]:
        if self._sessionmaker is None:
            from src.infrastructure.persistence.database import get_sessionmaker

            self._sessionmaker = get_sessionmaker()
        return self._sessionmaker

    async def save(self, memory: HiringAgentMemory) -> None:
        """Insert or update the run's memory row (idempotent upsert)."""
        async with self._sm()() as session, session.begin():
            obj = await session.get(HiringAgentMemoryModel, memory.run_id)
            if obj is None:
                obj = HiringAgentMemoryModel(
                    id=memory.run_id,
                    tenant_id=memory.tenant_id,
                    created_at=memory.created_at,
                )
                session.add(obj)
            obj.tenant_id = memory.tenant_id
            obj.status = memory.status.value
            obj.current_state = memory.current_state
            obj.completed_steps = list(memory.completed_steps)
            obj.tool_outputs = list(memory.tool_outputs)
            obj.llm_reasoning = list(memory.llm_reasoning)
            obj.conversation = list(memory.conversation)
            obj.candidate_decisions = list(memory.candidate_decisions)
            obj.execution = (
                memory.execution.model_dump(mode="json") if memory.execution else None
            )
            obj.error = memory.error
            obj.updated_at = memory.updated_at

    async def get(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID
    ) -> HiringAgentMemory | None:
        async with self._sm()() as session:
            obj = await session.get(HiringAgentMemoryModel, run_id)
        if obj is None or obj.tenant_id != tenant_id:
            return None
        return self._to_domain(obj)

    async def list_for_tenant(
        self, tenant_id: uuid.UUID, limit: int = 50
    ) -> list[HiringAgentMemory]:
        """Recent runs for a tenant, newest first (for the execution history view)."""
        async with self._sm()() as session:
            stmt = (
                select(HiringAgentMemoryModel)
                .where(HiringAgentMemoryModel.tenant_id == tenant_id)
                .order_by(HiringAgentMemoryModel.updated_at.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
        return [self._to_domain(r) for r in rows]

    async def find_resumable(
        self, tenant_id: uuid.UUID | None = None
    ) -> list[HiringAgentMemory]:
        """Runs left in a non-terminal state — candidates for resume."""
        async with self._sm()() as session:
            stmt = select(HiringAgentMemoryModel).where(
                HiringAgentMemoryModel.status.in_(_RESUMABLE)
            )
            if tenant_id is not None:
                stmt = stmt.where(HiringAgentMemoryModel.tenant_id == tenant_id)
            rows = (await session.execute(stmt)).scalars().all()
        return [self._to_domain(r) for r in rows]

    @staticmethod
    def _to_domain(obj: HiringAgentMemoryModel) -> HiringAgentMemory:
        from src.hiring_agent.types.execution import ExecutionCursor

        return HiringAgentMemory(
            run_id=obj.id,
            tenant_id=obj.tenant_id,
            status=HiringMemoryStatus(obj.status),
            current_state=obj.current_state,
            completed_steps=list(obj.completed_steps or []),
            tool_outputs=list(obj.tool_outputs or []),
            llm_reasoning=list(obj.llm_reasoning or []),
            conversation=list(obj.conversation or []),
            candidate_decisions=list(obj.candidate_decisions or []),
            execution=ExecutionCursor(**obj.execution) if obj.execution else None,
            error=obj.error,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )
