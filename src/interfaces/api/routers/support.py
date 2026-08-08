"""Report Issue — bug reports and feature requests from inside the app.

The report is persisted first and emailed second, deliberately: email is the
part that can fail (no API key, provider outage), and losing what a frustrated
user just typed because of that would be the worst possible outcome. A report
whose email didn't go out still shows in the admin list with `email_sent=false`.
"""

from __future__ import annotations

import html
import uuid

from fastapi import APIRouter, HTTPException, Request

from src.config.settings import get_settings
from src.domain.support.entities import (
    ALL_PRIORITIES,
    ALL_REPORT_TYPES,
    PRIORITY_LABELS,
    REPORT_TYPE_LABELS,
    IssueReport,
)
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep, PrincipalDep
from src.interfaces.api.schemas import (
    CreateIssueReportRequest,
    IssueOptionsResponse,
    IssueReportResponse,
)

router = APIRouter(prefix="/issues", tags=["support"])


def _to_response(report: IssueReport) -> IssueReportResponse:
    return IssueReportResponse(
        id=report.id,
        name=report.name,
        email=report.email,
        phone=report.phone,
        report_type=report.report_type,  # type: ignore[arg-type]
        priority=report.priority,  # type: ignore[arg-type]
        subject=report.subject,
        description=report.description,
        status=report.status,  # type: ignore[arg-type]
        page_url=report.page_url,
        email_sent=report.email_sent,
        created_at=report.created_at,
    )


def _email_html(report: IssueReport, tenant_id: uuid.UUID) -> str:
    """Everything triage needs without a reply-and-ask round trip.

    User-supplied values are HTML-escaped: this lands in someone's inbox, and a
    description containing markup shouldn't be able to shape that email.
    """
    esc = html.escape
    return (
        f"<h2>{esc(report.subject)}</h2>"
        f"<p><strong>Type:</strong> {esc(REPORT_TYPE_LABELS[report.report_type])}<br>"
        f"<strong>Priority:</strong> {esc(PRIORITY_LABELS[report.priority])}</p>"
        f"<p><strong>From:</strong> {esc(report.name)} &lt;{esc(report.email)}&gt;"
        + (f"<br><strong>Phone:</strong> {esc(report.phone)}" if report.phone else "")
        + f"<br><strong>Tenant:</strong> {tenant_id}</p>"
        + (f"<p><strong>Page:</strong> {esc(report.page_url)}</p>" if report.page_url else "")
        + "<h3>Description</h3>"
        f"<pre style='white-space:pre-wrap;font-family:inherit'>{esc(report.description)}</pre>"
        + (
            f"<p style='color:#888;font-size:12px'>User agent: {esc(report.user_agent)}</p>"
            if report.user_agent
            else ""
        )
    )


@router.get("/options", response_model=IssueOptionsResponse)
async def issue_options(principal: PrincipalDep) -> IssueOptionsResponse:
    """Dropdown contents, so the labels live in the domain rather than being
    duplicated in the form."""
    settings = get_settings()
    return IssueOptionsResponse(
        report_types=[{"value": t, "label": REPORT_TYPE_LABELS[t]} for t in ALL_REPORT_TYPES],
        priorities=[{"value": p, "label": PRIORITY_LABELS[p]} for p in ALL_PRIORITIES],
        support_email_configured=bool(settings.support_email and settings.resend_enabled),
    )


@router.post("", response_model=IssueReportResponse, status_code=201)
async def create_issue(
    body: CreateIssueReportRequest,
    request: Request,
    principal: PrincipalDep,
    container: ContainerDep,
) -> IssueReportResponse:
    report = IssueReport(
        tenant_id=principal.tenant_id,
        name=body.name,
        email=str(body.email),
        phone=body.phone,
        report_type=body.report_type,
        priority=body.priority,
        subject=body.subject,
        description=body.description,
        page_url=body.page_url,
        user_agent=request.headers.get("user-agent", ""),
    ).normalized()

    if (error := report.validation_error()) is not None:
        raise HTTPException(status_code=400, detail=error)

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.issue_reports.add(report)
        await uow.commit()

    settings = get_settings()
    if settings.support_email and container.email.enabled:
        try:
            sent = await container.email.send(
                to=settings.support_email,
                subject=report.email_subject(),
                html=_email_html(report, principal.tenant_id),
            )
        except Exception:  # noqa: BLE001 — the report is already saved; never 500 on this
            sent = False
        if sent:
            report.email_sent = True
            async with container.unit_of_work() as uow:
                uow.set_tenant_scope(principal.tenant_id)
                await uow.issue_reports.mark_email_sent(report.id, True)
                await uow.commit()

    return _to_response(report)


@router.get("", response_model=list[IssueReportResponse])
async def list_issues(
    principal: AdminPrincipalDep, container: ContainerDep
) -> list[IssueReportResponse]:
    """This tenant's own reports — so a team can see what they've already filed
    instead of duplicating it."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        reports = await uow.issue_reports.list_for_tenant(principal.tenant_id)
    return [_to_response(r) for r in reports]
