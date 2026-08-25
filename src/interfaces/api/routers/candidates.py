"""Candidates — every WhatsApp contact across every connected number, in one
tenant-wide, read-oriented view.

Where an HR user goes to open "the candidate I talked to last week" and see
the transcript and whatever documents (resume, marksheet, degree) they sent,
without needing to remember which number the conversation happened to land
on. The per-number inbox (`whatsapp_web.py`) answers "what's new on this
number"; this answers "what do I know about this person".

Reuses the existing per-conversation endpoints in `whatsapp_web.py` for the
transcript, attachments, and reply — those are already scoped by tenant alone
(`_owned_conversation` filters on `tenant_id`, not on which number owns the
thread), so nothing new was needed there. This router only adds the
tenant-wide list, plus the channel/number label each conversation needs to
show which number it came in on.
"""

from __future__ import annotations

import uuid

from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep
from src.interfaces.api.schemas import CandidatePageResponse, CandidateResponse
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/candidates", tags=["candidates"])

_MAX_PAGE_SIZE = 100


@router.get("", response_model=CandidatePageResponse)
async def list_candidates(
    principal: AdminPrincipalDep,
    container: ContainerDep,
    search: str = Query("", max_length=120),
    has_attachment: bool | None = None,
    unread_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=_MAX_PAGE_SIZE),
) -> CandidatePageResponse:
    offset = (page - 1) * page_size

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        rows = await uow.whatsapp_conversations.list_for_tenant(
            principal.tenant_id,
            search=search,
            has_attachment=has_attachment,
            unread_only=unread_only,
            limit=page_size,
            offset=offset,
        )
        total = await uow.whatsapp_conversations.count_for_tenant(
            principal.tenant_id,
            search=search,
            has_attachment=has_attachment,
            unread_only=unread_only,
        )
        # Every number this tenant has, so each conversation can be labelled
        # with where it came in — the same lookup broadcasts.py:list_senders
        # builds for the same reason (one list, two channel kinds).
        channels = {
            c.id: c for c in await uow.whatsapp_channels.list_for_tenant(principal.tenant_id)
        }
        sessions = {
            s.id: s
            for s in await uow.whatsapp_web_sessions.list_for_tenant(principal.tenant_id)
        }
        counts = await uow.chats.message_counts(
            principal.tenant_id, [r.session_id for r in rows]
        )

    candidates = [_to_response(row, channels, sessions, counts) for row in rows]
    return CandidatePageResponse(candidates=candidates, total=total, page=page, page_size=page_size)


@router.get("/{conversation_id}", response_model=CandidateResponse)
async def get_candidate(
    conversation_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> CandidateResponse:
    """One candidate, for their profile page.

    Exists so the profile survives a refresh or a shared link rather than
    depending on the grid having been loaded first.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        row = await uow.whatsapp_conversations.get_by_id(principal.tenant_id, conversation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        channels = {
            c.id: c for c in await uow.whatsapp_channels.list_for_tenant(principal.tenant_id)
        }
        sessions = {
            s.id: s
            for s in await uow.whatsapp_web_sessions.list_for_tenant(principal.tenant_id)
        }
        counts = await uow.chats.message_counts(principal.tenant_id, [row.session_id])

    return _to_response(row, channels, sessions, counts)


def _to_response(row, channels: dict, sessions: dict, counts: dict) -> CandidateResponse:
    channel = channels.get(row.whatsapp_channel_id)
    session = sessions.get(row.whatsapp_channel_id)
    if channel is not None:
        channel_kind, channel_label, session_id = "cloud_api", f"{channel.phone_number} · Cloud API", None
    elif session is not None:
        channel_kind = "personal"
        channel_label = (
            f"{session.phone_number or session.display_name or 'Personal WhatsApp'} · Phone WhatsApp"
        )
        session_id = session.id
    else:
        # The number this conversation started on was since disconnected or
        # deleted. Still worth showing — losing a candidate's history because
        # their inbound number was later removed would be a bad trade.
        channel_kind, channel_label, session_id = "personal", "Number no longer connected", None

    return CandidateResponse(
        id=row.id,
        phone_number=row.phone_number,
        display_name=row.display_name,
        last_message_at=row.last_message_at,
        last_message_preview=row.last_message_preview,
        unread_count=row.unread_count,
        has_attachment=row.has_attachment,
        auto_reply=row.auto_reply,
        channel_kind=channel_kind,
        channel_label=channel_label,
        session_id=session_id,
        message_count=counts.get(row.session_id, (0, 0))[0],
        document_count=counts.get(row.session_id, (0, 0))[1],
        followups_sent=row.followups_sent,
        awaiting_reply=row.awaiting_reply_since is not None,
    )
