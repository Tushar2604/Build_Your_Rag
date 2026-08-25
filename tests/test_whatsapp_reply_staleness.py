"""Guard: a campaign reply that arrives during a bridge reconnect is answered.

The reported symptom was "I start a campaign, the message goes out, the contact
replies, and the agent never answers" — while manually typed messages still
sent fine, which is what made it look like the assistant was broken rather than
the delivery path.

The cause was a flag with a misleading name. Baileys emits `messages.upsert`
with `type: "append"` whenever `node.attrs.offline` is set (see
lib/Socket/messages-recv.js) — that is, for anything WhatsApp *queued while the
socket was down* and flushed on reconnect. The bridge mapped that to
`synced: true`, and the API treated `synced` as an absolute veto on replying.

On a host whose bridge sleeps or restarts (a free tier, a redeploy), most
replies land during exactly such a reconnect, so they were stored in the inbox
and then silently never answered.

The flag was never needed for its stated purpose: genuine history backfill
arrives over `messaging-history.set` and is posted to `/bridge-history`, a
different endpoint that never reaches the reply path at all. So answerability
is decided from the message's own age instead.
"""

from __future__ import annotations

import time

from src.interfaces.api.routers.whatsapp_web import (
    _MAX_REPLY_AGE_SECONDS,
    _too_stale_to_answer,
)
from src.interfaces.api.schemas import BridgeEventRequest

SESSION = "11111111-1111-1111-1111-111111111111"


def _event(**kwargs) -> BridgeEventRequest:
    return BridgeEventRequest(
        session_id=SESSION,
        event="message",
        direction="in",
        text="yes, I'm interested",
        **kwargs,
    )


def test_a_reply_flushed_on_reconnect_is_still_answered() -> None:
    """The regression itself: `synced` must not silence a fresh message."""
    just_now = int(time.time()) - 5
    assert _too_stale_to_answer(_event(synced=True, timestamp=just_now)) is False


def test_a_reply_held_for_an_hour_is_still_answered() -> None:
    """A sleeping free-tier bridge can hold a reply a long time. The contact is
    still waiting on an answer, so this must not be treated as backfill."""
    an_hour_ago = int(time.time()) - 3600
    assert _too_stale_to_answer(_event(synced=True, timestamp=an_hour_ago)) is False


def test_a_genuinely_old_message_is_not_answered() -> None:
    """The failure the gate actually exists to prevent — answering into a
    conversation that has long since moved on."""
    long_ago = int(time.time()) - (_MAX_REPLY_AGE_SECONDS + 60)
    assert _too_stale_to_answer(_event(synced=True, timestamp=long_ago)) is True
    # Age decides it, not the flag: an old message is stale either way.
    assert _too_stale_to_answer(_event(synced=False, timestamp=long_ago)) is True


def test_a_missing_timestamp_does_not_block_a_reply() -> None:
    """An older bridge, or a message shape Baileys did not stamp, reports 0.

    Staying silent is the failure operators actually hit, so an unknown age is
    treated as answerable rather than as backfill.
    """
    assert _too_stale_to_answer(_event(synced=True, timestamp=0)) is False
    assert _too_stale_to_answer(_event(synced=True)) is False


def test_a_live_message_is_answered() -> None:
    assert _too_stale_to_answer(_event(timestamp=int(time.time()))) is False
