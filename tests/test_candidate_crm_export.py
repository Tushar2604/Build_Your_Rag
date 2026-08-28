"""Unit tests for "send this candidate to my CRM".

Covers the two halves that can be wrong without anything crashing: the payload
a CRM actually receives (a no-code mapping step reads this, so a renamed or
missing key is a silent data loss), and the header handling on the sender (an
Authorization header that could displace the HMAC signature would make the
signature decorative).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from src.domain.chat.entities import Message, MessageRole
from src.domain.integration.catalogue import get_spec, redact, validate_credentials
from src.domain.shared.identifiers import SessionId, TenantId, new_id
from src.infrastructure.messaging.webhook import WebhookSender, sign_payload
from src.interfaces.api.routers.candidates import (
    _CRM_INTEGRATION_ID,
    _crm_payload,
    _host_of,
)
from src.interfaces.api.schemas import CandidateResponse

TENANT = TenantId(new_id())
SESSION = SessionId(new_id())
START = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


class _Principal:
    tenant_id = TENANT


def _msg(role: MessageRole, content: str, minutes: int, **media) -> Message:
    return Message(
        session_id=SESSION,
        tenant_id=TENANT,
        role=role,
        content=content,
        created_at=START + timedelta(minutes=minutes),
        **media,
    )


def _candidate(**overrides) -> CandidateResponse:
    base = {
        "id": uuid.uuid4(),
        "phone_number": "+919876543210",
        "display_name": "Priya Sharma",
        "last_message_at": START + timedelta(minutes=30),
        "last_message_preview": "Sent my resume",
        "unread_count": 2,
        "has_attachment": True,
        "auto_reply": True,
        "channel_kind": "personal",
        "channel_label": "+911234567890 · Phone WhatsApp",
        "session_id": uuid.uuid4(),
        "message_count": 4,
        "document_count": 1,
        "followups_sent": 1,
        "awaiting_reply": False,
    }
    return CandidateResponse(**{**base, **overrides})


def _thread() -> list[Message]:
    return [
        _msg(MessageRole.ASSISTANT, "Hi! Are you open to a backend role?", 0),
        _msg(MessageRole.USER, "Yes — my portfolio is at https://priya.dev/work.", 5),
        _msg(
            MessageRole.USER,
            "Resume attached.",
            10,
            media_kind="document",
            media_mime_type="application/pdf",
            media_filename="priya-resume.pdf",
            media_storage_key="r2/abc",
            media_size_bytes=184_320,
        ),
        _msg(MessageRole.ASSISTANT, "Got it, thanks!", 30),
    ]


# --- The payload a CRM receives ---


def test_payload_carries_the_identity_a_crm_needs_to_create_a_record() -> None:
    candidate = _candidate()
    payload = _crm_payload(_Principal(), candidate, _thread())

    assert payload["event"] == "candidate.exported"
    assert payload["tenant_id"] == str(TENANT)
    contact = payload["candidate"]
    assert contact["name"] == "Priya Sharma"
    assert contact["phone_number"] == "+919876543210"
    assert contact["id"] == str(candidate.id)


def test_first_contacted_at_is_the_start_of_the_thread_not_the_end() -> None:
    # A CRM plotting "when did this lead enter the funnel" reads this field;
    # handing it the newest message would date every lead to today.
    payload = _crm_payload(_Principal(), _candidate(), _thread())
    assert payload["candidate"]["first_contacted_at"] == START


def test_documents_are_a_manifest_and_never_carry_the_bytes() -> None:
    payload = _crm_payload(_Principal(), _candidate(), _thread())
    assert len(payload["documents"]) == 1
    doc = payload["documents"][0]
    assert doc["filename"] == "priya-resume.pdf"
    assert doc["size_bytes"] == 184_320
    assert doc["stored"] is True
    # The attachment stays behind auth: a storage key in a CRM record would be
    # a credential leaked into a system with a different access model.
    assert "media_storage_key" not in doc
    assert "storage_key" not in doc


def test_links_shared_are_deduplicated_and_stripped_of_sentence_punctuation() -> None:
    messages = _thread() + [
        _msg(MessageRole.USER, "Again: https://priya.dev/work.", 40),
        _msg(MessageRole.USER, "Also (https://github.com/priya).", 41),
    ]
    payload = _crm_payload(_Principal(), _candidate(), messages)
    assert payload["links_shared"] == ["https://priya.dev/work", "https://github.com/priya"]


def test_transcript_direction_follows_the_message_role() -> None:
    payload = _crm_payload(_Principal(), _candidate(), _thread())
    assert [m["direction"] for m in payload["transcript"]] == ["out", "in", "in", "out"]


def test_a_short_thread_is_not_flagged_as_truncated() -> None:
    payload = _crm_payload(_Principal(), _candidate(), _thread())
    assert payload["transcript_truncated"] is False


def test_a_full_page_of_messages_says_it_was_truncated() -> None:
    # The receiver stores this as "the transcript"; it has to be able to tell
    # a complete one from the tail of a long one.
    from src.interfaces.api.routers.candidates import _MAX_EXPORT_MESSAGES

    messages = [_msg(MessageRole.USER, f"m{i}", i) for i in range(_MAX_EXPORT_MESSAGES)]
    payload = _crm_payload(_Principal(), _candidate(), messages)
    assert payload["transcript_truncated"] is True


def test_status_reflects_whether_a_human_has_taken_the_thread_over() -> None:
    assert (
        _crm_payload(_Principal(), _candidate(auto_reply=False), [])["candidate"]["status"]
        == "handled_by_human"
    )
    assert (
        _crm_payload(_Principal(), _candidate(auto_reply=True), [])["candidate"]["status"]
        == "assistant_replying"
    )


def test_an_empty_thread_exports_without_inventing_a_first_contact_date() -> None:
    payload = _crm_payload(_Principal(), _candidate(), [])
    assert payload["candidate"]["first_contacted_at"] is None
    assert payload["transcript"] == []
    assert payload["documents"] == []


# --- What the UI is told about the destination ---


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://hooks.zapier.com/hooks/catch/1/secret", "hooks.zapier.com"),
        ("https://crm.acme.co.uk:8443/intake", "crm.acme.co.uk:8443"),
        ("", ""),
    ],
)
def test_only_the_host_is_ever_shown(url: str, expected: str) -> None:
    # The path of a catch-hook URL is its credential, and the destination is
    # readable by anyone who can see a candidate.
    assert _host_of(url) == expected
    assert "secret" not in _host_of(url)


# --- The integration the export reads its destination from ---


def test_the_crm_integration_is_wired_and_takes_an_https_endpoint() -> None:
    spec = get_spec(_CRM_INTEGRATION_ID)
    assert spec is not None
    # Honesty rule: an unwired card can't be connected, and the export would
    # then have no destination to read.
    assert spec.wired is True

    assert validate_credentials(spec, {"webhook_url": "http://crm.local/hook"}).error
    assert validate_credentials(spec, {"webhook_url": ""}).error
    assert validate_credentials(spec, {"webhook_url": "https://crm.local/hook"}).error is None


def test_the_auth_header_is_optional_and_never_echoed_back() -> None:
    spec = get_spec(_CRM_INTEGRATION_ID)
    assert spec is not None

    result = validate_credentials(
        spec, {"webhook_url": "https://crm.local/hook", "auth_header": "Bearer sk_live_xyz"}
    )
    assert result.error is None
    assert result.config["auth_header"] == "Bearer sk_live_xyz"
    assert "sk_live_xyz" not in redact(spec, result.config)["auth_header"]


# --- Delivery ---


class _FakeResponse:
    status_code = 200
    text = "ok"


class _FakeClient:
    def __init__(self, sink: dict) -> None:
        self._sink = sink

    async def post(self, url, content=None, headers=None):
        self._sink.update(url=url, body=content, headers=headers)
        return _FakeResponse()


@pytest.fixture
def sent(monkeypatch) -> dict:
    sink: dict = {}

    async def fake_get_client(*_args, **_kwargs):
        return _FakeClient(sink)

    monkeypatch.setattr(
        "src.infrastructure.messaging.webhook.get_client", fake_get_client
    )
    return sink


def test_an_auth_header_rides_along_with_a_valid_signature(sent: dict) -> None:
    sender = WebhookSender("jwt-secret")
    delivered, error = asyncio.run(
        sender.send(
            "https://crm.local/hook",
            {"event": "candidate.exported"},
            extra_headers={"Authorization": "Bearer sk_live_xyz"},
        )
    )

    assert delivered is True and error == ""
    headers = sent["headers"]
    assert headers["Authorization"] == "Bearer sk_live_xyz"
    assert headers["X-Signature"] == sign_payload(
        "jwt-secret", headers["X-Signature-Timestamp"], sent["body"]
    )


def test_extra_headers_cannot_displace_the_signature(sent: dict) -> None:
    # Otherwise a stored config could quietly turn the signature off, and every
    # receiver verifying it would start trusting a forged value instead.
    sender = WebhookSender("jwt-secret")
    asyncio.run(
        sender.send(
            "https://crm.local/hook",
            {"event": "candidate.exported"},
            extra_headers={"X-Signature": "forged", "X-Signature-Timestamp": "0"},
        )
    )

    headers = sent["headers"]
    assert headers["X-Signature"] != "forged"
    assert headers["X-Signature-Timestamp"] != "0"


def test_a_blank_auth_header_is_omitted_rather_than_sent_empty(sent: dict) -> None:
    sender = WebhookSender("jwt-secret")
    asyncio.run(
        sender.send("https://crm.local/hook", {"a": 1}, extra_headers={"Authorization": ""})
    )
    assert "Authorization" not in sent["headers"]


def test_no_extra_headers_behaves_exactly_as_before(sent: dict) -> None:
    # Post-call delivery calls this same sender without the new argument.
    sender = WebhookSender("jwt-secret")
    delivered, _ = asyncio.run(sender.send("https://crm.local/hook", {"a": 1}))
    assert delivered is True
    assert "Authorization" not in sent["headers"]
    assert sent["headers"]["Content-Type"] == "application/json"
