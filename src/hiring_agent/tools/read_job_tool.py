"""ReadJobTool — ingest a job description and extract its Job Context.

Unlike the other hiring tools (which delegate to an MCP server), ReadJob runs
its ingestion IN-PROCESS: it reuses the chatbot ingestion pipeline under the
caller's tenant scope (from `ToolContext.tenant_id`), which the per-call stdio
MCP subprocess cannot carry safely. See ReadJobService for the pipeline reuse.

Inputs (via kwargs):
    text        : str  — raw job-description text, OR
    pdf_base64  : str  — a base64-encoded job-description PDF
    filename    : str  — optional display filename
When neither `text` nor `pdf_base64` is supplied (e.g. the workflow simulation
passing only a `job_id`), the tool returns a benign, no-op observation so the
surrounding workflow still advances.
"""

from __future__ import annotations

import base64
from typing import Any

import structlog

from src.application.agent.tools import ToolContext, ToolResult, ToolSpec

log = structlog.get_logger(__name__)


class ReadJobTool:
    spec = ToolSpec(
        name="read_job",
        description=(
            "Ingest a job description (raw text or a base64-encoded PDF) into the "
            "tenant's searchable corpus using the standard ingestion pipeline, then "
            "extract a structured Job Context: required skills, experience, "
            "responsibilities, preferred skills, and interview stages."
        ),
        parameters={
            "text": {
                "type": "string",
                "description": "Raw job-description text (use this OR pdf_base64).",
            },
            "pdf_base64": {
                "type": "string",
                "description": "Base64-encoded job-description PDF (use this OR text).",
            },
            "filename": {
                "type": "string",
                "description": "Optional display filename for the ingested document.",
            },
            "job_id": {
                "type": "string",
                "description": "Optional identifier; used only for logging/correlation.",
            },
        },
    )

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        text = kwargs.get("text")
        pdf_base64 = kwargs.get("pdf_base64")
        filename = kwargs.get("filename")

        if not text and not pdf_base64:
            # No content to ingest — keep the workflow moving without erroring.
            return ToolResult(
                observation=(
                    "No job description content supplied. Pass `text` or "
                    "`pdf_base64` to ingest and analyse a job description."
                ),
                data={"skipped": True},
                ok=True,
            )

        try:
            pdf_bytes = base64.b64decode(pdf_base64) if pdf_base64 else None
        except Exception as exc:  # noqa: BLE001 - bad client input
            return ToolResult(
                observation=f"[read_job error] pdf_base64 is not valid base64: {exc}",
                data={"error": str(exc)},
                ok=False,
            )

        # Lazily reach the composition root — mirrors the lazy client access in
        # BaseMCPTool and avoids building the container at import time.
        from src.config.container import get_container
        from src.hiring_agent.services.read_job_service import ReadJobService

        container = get_container()
        service = ReadJobService(
            container.unit_of_work,
            container.storage,
            container.parser,
            container.chunker,
            container.embedder,
            container.llm,
        )

        log.info(
            "hiring.tool.read_job.invoke",
            tenant=str(ctx.tenant_id),
            has_pdf=pdf_bytes is not None,
            job_id=kwargs.get("job_id"),
        )

        try:
            result = await service.execute(
                ctx.tenant_id,
                text=text,
                pdf_bytes=pdf_bytes,
                filename=filename,
            )
        except Exception as exc:  # noqa: BLE001 - surface as a handled tool error
            log.error(
                "hiring.tool.read_job.failed",
                tenant=str(ctx.tenant_id),
                error=str(exc),
            )
            return ToolResult(
                observation=f"[read_job error] {type(exc).__name__}: {exc}",
                data={"error": str(exc), "error_type": type(exc).__name__},
                ok=False,
            )

        jc = result.job_context
        observation = (
            f"Job description ingested (document {result.document_id}, "
            f"{result.chunk_count} chunks, status {result.status}). "
            f"Required skills: {', '.join(jc.required_skills) or 'n/a'}. "
            f"Experience: {jc.experience or 'n/a'}. "
            f"{len(jc.responsibilities)} responsibilities, "
            f"{len(jc.preferred_skills)} preferred skills, "
            f"{len(jc.interview_stages)} interview stages."
        )
        if result.extraction_note:
            observation += f" Note: {result.extraction_note}"

        return ToolResult(observation=observation, data=result.model_dump(), ok=True)
