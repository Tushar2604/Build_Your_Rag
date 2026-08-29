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

import re
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query

from src.domain.chat.entities import MessageRole
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep
from src.interfaces.api.schemas import (
    CandidatePageResponse,
    CandidateResponse,
    CandidateThreadResponse,
    ConnectedNumberResponse,
    CrmDestinationResponse,
    CrmExportResponse,
)

router = APIRouter(prefix="/candidates", tags=["candidates"])

_MAX_PAGE_SIZE = 100

# The integration whose credentials the CRM export uses. A generic signed
# webhook rather than a named vendor: "whatever CRM we have" is the actual
# requirement, and every CRM can be handed an HTTPS endpoint (natively or via
# Zapier/Make/n8n) where none of them share an object model.
_CRM_INTEGRATION_ID = "crm_webhook"

# How much transcript travels with a candidate. Enough to be the record of the
# conversation, bounded so one long thread cannot produce a multi-megabyte POST
# that a CRM's intake silently truncates or rejects.
_MAX_EXPORT_MESSAGES = 200

_URL_RE = re.compile(r"https?://[^\s<>\"']+")


@router.get("", response_model=CandidatePageResponse)
async def list_candidates(
    principal: AdminPrincipalDep,
    container: ContainerDep,
    search: str = Query("", max_length=120),
    has_attachment: bool | None = None,
    unread_only: bool = False,
    number_id: uuid.UUID | None = Query(
        None,
        description="Show only people on this connected WhatsApp number "
        "(a linked session id or a Cloud API channel id). Omit for all numbers.",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=_MAX_PAGE_SIZE),
) -> CandidatePageResponse:
    """People, one row each.

    Grouped by contact rather than by thread. A contact who reached two
    connected numbers has a real conversation on each, and listing threads
    showed them twice — which read as a duplicate even though neither copy was
    wrong. The card represents whichever thread is most recently active and
    carries the rest in `threads`, so the profile can switch between numbers
    instead of one of them being thrown away.
    """
    offset = (page - 1) * page_size

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        rows = await uow.whatsapp_conversations.list_contacts_for_tenant(
            principal.tenant_id,
            search=search,
            has_attachment=has_attachment,
            unread_only=unread_only,
            owner_id=number_id,
            limit=page_size,
            offset=offset,
        )
        total = await uow.whatsapp_conversations.count_contacts_for_tenant(
            principal.tenant_id,
            search=search,
            has_attachment=has_attachment,
            unread_only=unread_only,
            owner_id=number_id,
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
        siblings = {
            row.id: await uow.whatsapp_conversations.threads_for_contact(
                principal.tenant_id, row.phone_number
            )
            for row in rows
        }
        counts = await uow.chats.message_counts(
            principal.tenant_id,
            [t.session_id for threads in siblings.values() for t in threads],
        )

    candidates = [
        _to_response(row, channels, sessions, counts, siblings.get(row.id, [])) for row in rows
    ]
    return CandidatePageResponse(candidates=candidates, total=total, page=page, page_size=page_size)


@router.get("/numbers", response_model=list[ConnectedNumberResponse])
async def connected_numbers(
    principal: AdminPrincipalDep, container: ContainerDep
) -> list[ConnectedNumberResponse]:
    """The numbers the list can be filtered by, with how many people are on each.

    Its own endpoint rather than a field on the page response: the picker has
    to stay put while you page and search through the list under it, and a
    filter whose own options change as you use it is unusable.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        channels = await uow.whatsapp_channels.list_for_tenant(principal.tenant_id)
        sessions = await uow.whatsapp_web_sessions.list_for_tenant(principal.tenant_id)
        out: list[ConnectedNumberResponse] = []
        for ws in sessions:
            out.append(
                ConnectedNumberResponse(
                    id=ws.id,
                    kind="personal",
                    phone_number=ws.phone_number,
                    label=ws.display_name or ws.phone_number or "Pairing…",
                    connected=ws.status == "linked",
                    contact_count=await uow.whatsapp_conversations.count_contacts_for_tenant(
                        principal.tenant_id, owner_id=ws.id
                    ),
                )
            )
        for channel in channels:
            out.append(
                ConnectedNumberResponse(
                    id=channel.id,
                    kind="cloud_api",
                    phone_number=channel.phone_number,
                    label=channel.phone_number,
                    connected=channel.status == "active",
                    contact_count=await uow.whatsapp_conversations.count_contacts_for_tenant(
                        principal.tenant_id, owner_id=channel.id
                    ),
                )
            )
    return out


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
        siblings = await uow.whatsapp_conversations.threads_for_contact(
            principal.tenant_id, row.phone_number
        )
        counts = await uow.chats.message_counts(
            principal.tenant_id, [t.session_id for t in siblings] or [row.session_id]
        )

    return _to_response(row, channels, sessions, counts, siblings)


def _label_for(owner_id, channels: dict, sessions: dict):
    """Which connected number a thread came in on, as (kind, label, session_id).

    Shared by the card and by each of its sibling threads, so the number is
    named the same way in the list and in the profile's number switcher.
    """
    channel = channels.get(owner_id)
    session = sessions.get(owner_id)
    if channel is not None:
        return "cloud_api", f"{channel.phone_number} · Cloud API", None
    if session is not None:
        label = session.phone_number or session.display_name or "Personal WhatsApp"
        return "personal", f"{label} · Phone WhatsApp", session.id
    # The number this conversation started on was since disconnected or
    # deleted. Still worth showing — losing a candidate's history because
    # their inbound number was later removed would be a bad trade.
    return "personal", "Number no longer connected", None


def _to_response(
    row, channels: dict, sessions: dict, counts: dict, siblings: list | None = None
) -> CandidateResponse:
    channel_kind, channel_label, session_id = _label_for(
        row.whatsapp_channel_id, channels, sessions
    )
    threads = [
        CandidateThreadResponse(
            conversation_id=t.id,
            **dict(
                zip(
                    ("channel_kind", "channel_label", "session_id"),
                    _label_for(t.whatsapp_channel_id, channels, sessions),
                    strict=True,
                )
            ),
            last_message_at=t.last_message_at,
            message_count=counts.get(t.session_id, (0, 0))[0],
            unread_count=t.unread_count,
        )
        for t in (siblings or [])
    ]

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
        threads=threads,
    )


# --- CRM export -------------------------------------------------------------
#
# "Open a candidate, press one button, and they are in my CRM." The destination
# is the tenant's `crm_webhook` integration, so the workspace configures it once
# on the Integrations page and every candidate becomes exportable — rather than
# each page growing its own URL field.
#
# Synchronous, unlike post-call delivery, which dispatches in the background.
# This one is a person pressing a button and waiting for an answer: told
# "queued" they would have no way to find out it never arrived, and the whole
# value of the button is knowing the record landed.


def _host_of(url: str) -> str:
    """The endpoint's host, for display. Never the path — for a catch-hook URL
    the path *is* the credential, and these responses are read by anyone who
    can see a candidate."""
    try:
        return urlsplit(url).netloc
    except ValueError:
        return ""


async def _crm_connection(container, tenant_id):
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(tenant_id)
        connection = await uow.tenant_integrations.get(tenant_id, _CRM_INTEGRATION_ID)
    if connection is None or not connection.enabled or not connection.webhook_url():
        return None
    return connection


@router.get("/crm/destination", response_model=CrmDestinationResponse)
async def crm_destination(
    principal: AdminPrincipalDep, container: ContainerDep
) -> CrmDestinationResponse:
    """Whether this workspace has a CRM wired up, so the UI can show a live
    button or a "connect your CRM first" hint instead of firing a request it
    already knows will fail."""
    connection = await _crm_connection(container, principal.tenant_id)
    if connection is None:
        return CrmDestinationResponse(connected=False)
    return CrmDestinationResponse(
        connected=True, endpoint_host=_host_of(connection.webhook_url())
    )


@router.post("/{conversation_id}/crm/export", response_model=CrmExportResponse)
async def export_candidate_to_crm(
    conversation_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> CrmExportResponse:
    """POST one candidate's whole record to the workspace's CRM endpoint.

    Returns the delivery outcome rather than raising on a rejected webhook: a
    CRM answering 422 is news about the CRM, not a failure of this request, and
    the operator needs to read what it said.
    """
    connection = await _crm_connection(container, principal.tenant_id)
    if connection is None:
        raise HTTPException(
            status_code=400,
            detail="No CRM is connected. Add your CRM endpoint under "
            "Integrations → Your CRM (Webhook) first.",
        )

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
        messages = await uow.chats.list_messages(
            principal.tenant_id, row.session_id, limit=_MAX_EXPORT_MESSAGES
        )

    candidate = _to_response(row, channels, sessions, counts)
    payload = _crm_payload(principal, candidate, messages)

    url = connection.webhook_url()
    auth_header = connection.config.get("auth_header", "")
    delivered, error = await container.webhook.send(
        url, payload, extra_headers={"Authorization": auth_header} if auth_header else None
    )
    host = _host_of(url)
    return CrmExportResponse(
        delivered=delivered,
        message=f"Sent to {host}." if delivered else error,
        endpoint_host=host,
    )


def _crm_payload(principal, candidate: CandidateResponse, messages: list) -> dict:
    """The record a CRM receives. Flat and self-describing: the receiving end is
    usually a no-code mapping step, and anything that needs a join to be
    understood there will not get mapped."""
    documents = [
        {
            "filename": msg.media_filename or "",
            "kind": msg.media_kind or "",
            "mime_type": msg.media_mime_type or "",
            "size_bytes": msg.media_size_bytes or 0,
            "received_at": msg.created_at,
            # The bytes stay behind auth — a CRM record gets the manifest, and
            # anyone who needs the file downloads it from the candidate's page.
            "stored": bool(msg.media_storage_key),
        }
        for msg in messages
        if msg.media_kind
    ]

    links: list[str] = []
    for msg in messages:
        for raw in _URL_RE.findall(msg.content or ""):
            url = raw.rstrip(".,;:!?)]}>")
            if url not in links:
                links.append(url)

    return {
        "event": "candidate.exported",
        "source": "Evara AI",
        "tenant_id": str(principal.tenant_id),
        "candidate": {
            "id": str(candidate.id),
            "name": candidate.display_name or "",
            "phone_number": candidate.phone_number,
            "channel": candidate.channel_label,
            "status": "handled_by_human" if not candidate.auto_reply else "assistant_replying",
            "first_contacted_at": messages[0].created_at if messages else None,
            "last_message_at": candidate.last_message_at,
            "last_message_preview": candidate.last_message_preview,
            "message_count": candidate.message_count,
            "document_count": candidate.document_count,
            "unread_count": candidate.unread_count,
            "followups_sent": candidate.followups_sent,
            "awaiting_reply": candidate.awaiting_reply,
        },
        "documents": documents,
        "links_shared": links,
        "transcript": [
            {
                "direction": "in" if msg.role == MessageRole.USER else "out",
                "content": msg.content,
                "at": msg.created_at,
            }
            for msg in messages
        ],
        # Says out loud that a long thread was trimmed, so a receiver storing
        # this as "the transcript" knows when it is only the tail of one.
        "transcript_truncated": len(messages) >= _MAX_EXPORT_MESSAGES,
    }
