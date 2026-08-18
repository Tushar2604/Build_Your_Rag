"""Campaign mode and sender selection.

A campaign now chooses two things it never used to: what happens when someone
replies, and which WhatsApp it sends from. Both change what real people receive,
so the tests here are about the branches that decide that — not the plumbing.
"""

from __future__ import annotations

import uuid

import pytest
from src.application.use_cases.broadcast import SendBroadcast
from src.domain.broadcast.entities import Broadcast, BroadcastRecipient
from src.domain.shared.identifiers import ChatbotId, TenantId

TENANT = TenantId(uuid.uuid4())


def _broadcast(**kw) -> Broadcast:
    defaults = {
        "tenant_id": TENANT,
        "chatbot_id": ChatbotId(uuid.uuid4()),
        "name": "March re-engagement",
        "message_template": "Hi {{first_name}}!",
        "whatsapp_channel_id": uuid.uuid4(),
    }
    defaults.update(kw)
    return Broadcast(**defaults)


class TestSenderSelection:
    def test_a_cloud_campaign_reports_its_channel(self) -> None:
        channel = uuid.uuid4()
        b = _broadcast(whatsapp_channel_id=channel, sender_kind="cloud_api")
        assert b.sender_id == channel

    def test_a_personal_campaign_reports_its_session(self) -> None:
        session = uuid.uuid4()
        b = _broadcast(
            whatsapp_channel_id=None, whatsapp_session_id=session, sender_kind="personal"
        )
        assert b.sender_id == session

    def test_a_personal_campaign_ignores_a_stray_channel_id(self) -> None:
        # Both columns exist; `sender_kind` is what decides, so a leftover value
        # in the other column can never silently send from the wrong number.
        b = _broadcast(
            whatsapp_channel_id=uuid.uuid4(),
            whatsapp_session_id=uuid.uuid4(),
            sender_kind="personal",
        )
        assert b.sender_id == b.whatsapp_session_id

    def test_a_campaign_with_no_sender_is_rejected(self) -> None:
        b = _broadcast(whatsapp_channel_id=None)
        assert b.validation_error() == "Choose the WhatsApp number this campaign sends from."


class TestMode:
    def test_broadcast_reply_answers(self) -> None:
        assert _broadcast(mode="broadcast_reply").replies_are_answered() is True

    def test_broadcast_only_does_not_answer(self) -> None:
        assert _broadcast(mode="broadcast").replies_are_answered() is False

    def test_existing_campaigns_default_to_replying(self) -> None:
        # That is what they were doing before mode existed; changing it silently
        # would leave contacts talking to nobody.
        assert _broadcast().mode == "broadcast_reply"


class FakeTwilio:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(self, **kwargs):
        self.calls.append(kwargs)
        return True, "SM123", ""


class FakeBridge:
    def __init__(self, *, enabled: bool = True, ok: bool = True) -> None:
        self.enabled = enabled
        self._ok = ok
        self.calls: list[tuple[str, str, str]] = []

    async def send_text(self, session_id: str, jid: str, text: str):
        self.calls.append((session_id, jid, text))
        return (True, "") if self._ok else (False, "socket closed")


class FakeChannel:
    id = uuid.uuid4()
    twilio_account_sid = "AC1"
    twilio_auth_token = "tok"
    phone_number = "+14155550100"


def _recipient(broadcast: Broadcast) -> BroadcastRecipient:
    return BroadcastRecipient(
        broadcast_id=broadcast.id,
        tenant_id=TENANT,
        phone_number="+919876543210",
        display_name="Asha Menon",
    )


class TestDelivery:
    """`_deliver` picks the transport; everything downstream is identical."""

    async def test_a_cloud_campaign_goes_through_twilio(self) -> None:
        twilio, bridge = FakeTwilio(), FakeBridge()
        sweep = SendBroadcast(None, twilio, "https://cb", bridge=bridge)
        b = _broadcast(sender_kind="cloud_api")

        ok, sid, error = await sweep._deliver(b, FakeChannel(), _recipient(b), "Hi Asha!")

        assert (ok, sid, error) == (True, "SM123", "")
        assert twilio.calls[0]["to_number"] == "+919876543210"
        assert bridge.calls == []

    async def test_a_personal_campaign_goes_through_the_bridge(self) -> None:
        twilio, bridge = FakeTwilio(), FakeBridge()
        sweep = SendBroadcast(None, twilio, "https://cb", bridge=bridge)
        session = uuid.uuid4()
        b = _broadcast(
            whatsapp_channel_id=None, whatsapp_session_id=session, sender_kind="personal"
        )

        ok, sid, error = await sweep._deliver(b, None, _recipient(b), "Hi Asha!")

        assert ok is True
        assert twilio.calls == []
        assert bridge.calls == [(str(session), "919876543210@s.whatsapp.net", "Hi Asha!")]

    async def test_the_jid_drops_the_plus(self) -> None:
        # WhatsApp JIDs are bare digits; a leading "+" addresses nobody and the
        # message is silently dropped by the socket.
        bridge = FakeBridge()
        sweep = SendBroadcast(None, FakeTwilio(), "", bridge=bridge)
        b = _broadcast(
            whatsapp_channel_id=None, whatsapp_session_id=uuid.uuid4(), sender_kind="personal"
        )

        await sweep._deliver(b, None, _recipient(b), "Hi")
        assert bridge.calls[0][1].startswith("91987")

    @pytest.mark.parametrize(
        "bridge", [None, FakeBridge(enabled=False)], ids=["missing", "disabled"]
    )
    async def test_an_unavailable_bridge_fails_the_send_explicitly(self, bridge) -> None:
        # Not an exception: one recipient failing must not abort the sweep for
        # everyone behind them in the queue.
        sweep = SendBroadcast(None, FakeTwilio(), "", bridge=bridge)
        b = _broadcast(
            whatsapp_channel_id=None, whatsapp_session_id=uuid.uuid4(), sender_kind="personal"
        )

        ok, _, error = await sweep._deliver(b, None, _recipient(b), "Hi")
        assert ok is False
        assert "bridge" in error.lower()

    async def test_a_bridge_failure_is_reported_not_raised(self) -> None:
        sweep = SendBroadcast(None, FakeTwilio(), "", bridge=FakeBridge(ok=False))
        b = _broadcast(
            whatsapp_channel_id=None, whatsapp_session_id=uuid.uuid4(), sender_kind="personal"
        )

        ok, _, error = await sweep._deliver(b, None, _recipient(b), "Hi")
        assert (ok, error) == (False, "socket closed")


class FakeChats:
    def __init__(self) -> None:
        self.sessions: list = []

    async def add_session(self, session) -> None:
        self.sessions.append(session)


class FakeConversations:
    def __init__(self) -> None:
        self.added: list = []

    async def get(self, owner_id, phone_number):
        return next(
            (
                c
                for c in self.added
                if c.whatsapp_channel_id == owner_id and c.phone_number == phone_number
            ),
            None,
        )

    async def add(self, conversation) -> None:
        self.added.append(conversation)

    async def update(self, conversation) -> None:
        # Already the same object the fake handed out, so there is nothing to
        # write back — but the real repository is called on the returning-
        # contact path (to start their follow-up clock) and must exist here.
        assert conversation in self.added


class FakeUow:
    def __init__(self) -> None:
        self.chats = FakeChats()
        self.whatsapp_conversations = FakeConversations()

    async def flush(self) -> None:
        pass


class TestConversationWiring:
    """`auto_reply` on the conversation is what makes the two modes differ.

    Both inbound paths (Twilio webhook and the personal bridge) read it, so a
    campaign that sets it wrong would answer messages it promised not to.
    """

    async def _create(self, mode: str, **kw) -> FakeUow:
        sweep = SendBroadcast(None, FakeTwilio(), "")
        b = _broadcast(mode=mode, **kw)
        uow = FakeUow()
        await sweep._ensure_conversation(uow, b, FakeChannel(), _recipient(b))
        return uow

    async def test_broadcast_reply_creates_an_answering_conversation(self) -> None:
        uow = await self._create("broadcast_reply")
        assert uow.whatsapp_conversations.added[0].auto_reply is True

    async def test_broadcast_only_creates_a_silent_conversation(self) -> None:
        # The conversation still exists — the outbound message belongs in the
        # log and a reply still counts in the funnel — it just is not answered.
        uow = await self._create("broadcast")
        conversation = uow.whatsapp_conversations.added[0]
        assert conversation.auto_reply is False
        assert len(uow.chats.sessions) == 1

    async def test_a_personal_campaign_keys_the_conversation_on_its_session(self) -> None:
        # The column holds either a channel id or a web-session id; keying a
        # personal campaign on the channel would lose the recipient's replies.
        session = uuid.uuid4()
        uow = await self._create(
            "broadcast_reply",
            whatsapp_channel_id=None,
            whatsapp_session_id=session,
            sender_kind="personal",
        )
        assert uow.whatsapp_conversations.added[0].whatsapp_channel_id == session

    async def test_a_returning_contact_keeps_their_existing_conversation(self) -> None:
        sweep = SendBroadcast(None, FakeTwilio(), "")
        b = _broadcast(mode="broadcast_reply")
        uow = FakeUow()
        recipient = _recipient(b)

        first = await sweep._ensure_conversation(uow, b, FakeChannel(), recipient)
        second = await sweep._ensure_conversation(uow, b, FakeChannel(), recipient)

        assert first == second
        assert len(uow.whatsapp_conversations.added) == 1
