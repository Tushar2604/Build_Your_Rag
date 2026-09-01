"""The WhatsApp Cloud API adapter: trust, parsing, and the outbound call.

The webhook is a public, unauthenticated URL that can put words into a
customer's WhatsApp thread. Everything here defends one of the three ways that
goes wrong in production:

  * a signature check written so that it can never pass (or never fail),
  * a parser that drops messages because Meta's envelope nests deeper than the
    example payload in the docs,
  * a send that reports success on a request Meta actually rejected.

Hermetic — no network, no database, no credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from src.infrastructure.messaging.whatsapp_cloud import (
    CloudWhatsAppSender,
    parse_webhook,
    verification_challenge,
    verify_meta_signature,
)

APP_SECRET = "test-app-secret"


def _signed(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestWebhookSignatures:
    """The only thing between an attacker and a customer's thread."""

    def test_a_genuine_delivery_is_accepted(self) -> None:
        body = b'{"object":"whatsapp_business_account"}'
        assert verify_meta_signature(body, _signed(body), APP_SECRET)

    def test_the_prefix_is_optional(self) -> None:
        # Documented as "sha256=<hex>", but tolerating a bare digest costs
        # nothing and saves an outage if Meta ever sends one.
        body = b'{"a":1}'
        bare = _signed(body).removeprefix("sha256=")
        assert verify_meta_signature(body, bare, APP_SECRET)

    def test_a_body_changed_in_transit_is_refused(self) -> None:
        body = b'{"amount":"10"}'
        signature = _signed(body)
        assert not verify_meta_signature(b'{"amount":"1000"}', signature, APP_SECRET)

    def test_another_apps_secret_is_refused(self) -> None:
        body = b'{"a":1}'
        assert not verify_meta_signature(body, _signed(body, "someone-elses"), APP_SECRET)

    def test_a_missing_signature_is_refused(self) -> None:
        assert not verify_meta_signature(b"{}", "", APP_SECRET)

    def test_no_configured_secret_refuses_everything(self) -> None:
        # The important direction. A deployment that forgot the secret must go
        # visibly deaf, not quietly accept unsigned posts — the second failure
        # is silent and its damage is real messages to real people.
        body = b"{}"
        assert not verify_meta_signature(body, _signed(body, ""), "")

    def test_whitespace_changes_the_digest(self) -> None:
        # Why the raw body is verified rather than the re-serialised JSON:
        # these two parse identically and sign differently, so a check written
        # against `json.dumps(await request.json())` never passes.
        compact = b'{"a":1}'
        spaced = b'{"a": 1}'
        assert json.loads(compact) == json.loads(spaced)
        assert not verify_meta_signature(spaced, _signed(compact), APP_SECRET)


class TestSubscriptionHandshake:
    def test_the_challenge_is_echoed_when_the_token_matches(self) -> None:
        assert verification_challenge("subscribe", "s3cret", "1158201444", "s3cret") == (
            "1158201444"
        )

    def test_a_wrong_token_is_refused(self) -> None:
        assert verification_challenge("subscribe", "guess", "1158201444", "s3cret") is None

    def test_an_unconfigured_deployment_refuses_rather_than_accepts(self) -> None:
        # Without this, a blank expected token would match a blank supplied one
        # and hand webhook verification to anybody who found the URL.
        assert verification_challenge("subscribe", "", "1158201444", "") is None

    def test_a_mode_we_did_not_ask_for_is_refused(self) -> None:
        assert verification_challenge("unsubscribe", "s3cret", "x", "s3cret") is None


def _envelope(*changes: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "200000000000002", "changes": list(changes)}],
    }


def _message_change(**message: object) -> dict:
    return {
        "field": "messages",
        "value": {
            "messaging_product": "whatsapp",
            "metadata": {
                "display_phone_number": "15550100001",
                "phone_number_id": "100000000000001",
            },
            "contacts": [{"profile": {"name": "Aisha"}, "wa_id": "971500000001"}],
            "messages": [
                {
                    "from": "971500000001",
                    "id": "wamid.ABC123",
                    "timestamp": "1756713600",
                    **message,
                }
            ],
        },
    }


class TestParsingTheEnvelope:
    def test_a_plain_text_message_comes_out_flat(self) -> None:
        parsed = parse_webhook(
            _envelope(_message_change(type="text", text={"body": "  I need an appointment  "}))
        )
        assert len(parsed.messages) == 1
        message = parsed.messages[0]
        assert message.text == "I need an appointment"
        assert message.from_number == "971500000001"
        assert message.phone_number_id == "100000000000001"
        assert message.message_id == "wamid.ABC123"
        assert message.contact_name == "Aisha"

    def test_a_tapped_reply_button_is_read_as_an_answer(self) -> None:
        # The booking assistant offers numbered options, so a tapped reply IS
        # the customer's answer. Reading only text.body would make it look deaf
        # to its own buttons.
        parsed = parse_webhook(
            _envelope(
                _message_change(
                    type="interactive",
                    interactive={
                        "type": "button_reply",
                        "button_reply": {"id": "opt_2", "title": "10:00 AM"},
                    },
                )
            )
        )
        assert parsed.messages[0].text == "10:00 AM"

    def test_a_list_selection_is_read_too(self) -> None:
        parsed = parse_webhook(
            _envelope(
                _message_change(
                    type="interactive",
                    interactive={
                        "type": "list_reply",
                        "list_reply": {"id": "svc_1", "title": "Root canal"},
                    },
                )
            )
        )
        assert parsed.messages[0].text == "Root canal"

    def test_a_template_quick_reply_is_read(self) -> None:
        parsed = parse_webhook(
            _envelope(_message_change(type="button", button={"text": "Confirm", "payload": "yes"}))
        )
        assert parsed.messages[0].text == "Confirm"

    def test_a_photo_arrives_with_no_text_but_is_still_a_message(self) -> None:
        # It must not be dropped: the operator's inbox should show that
        # something came in, even though the assistant cannot read it.
        parsed = parse_webhook(
            _envelope(_message_change(type="image", image={"id": "media-1"}))
        )
        assert len(parsed.messages) == 1
        assert parsed.messages[0].text == ""
        assert parsed.messages[0].kind == "image"

    def test_several_messages_in_one_delivery_all_survive(self) -> None:
        # Meta batches. Treating a POST as "the message" is how deliveries get
        # silently dropped exactly when traffic is highest.
        busy = _message_change(type="text", text={"body": "first"})
        busy["value"]["messages"].append(  # type: ignore[index]
            {
                "from": "971500000002",
                "id": "wamid.SECOND",
                "type": "text",
                "text": {"body": "second"},
            }
        )
        parsed = parse_webhook(_envelope(busy))
        assert [m.text for m in parsed.messages] == ["first", "second"]

    def test_delivery_receipts_are_lifted_out(self) -> None:
        parsed = parse_webhook(
            _envelope(
                {
                    "field": "messages",
                    "value": {
                        "metadata": {"phone_number_id": "100000000000001"},
                        "statuses": [
                            {
                                "id": "wamid.OUT1",
                                "status": "delivered",
                                "recipient_id": "971500000001",
                            }
                        ],
                    },
                }
            )
        )
        assert parsed.messages == []
        assert parsed.statuses[0].status == "delivered"
        assert parsed.statuses[0].message_id == "wamid.OUT1"

    def test_a_failure_receipt_carries_the_reason(self) -> None:
        parsed = parse_webhook(
            _envelope(
                {
                    "field": "messages",
                    "value": {
                        "metadata": {"phone_number_id": "1"},
                        "statuses": [
                            {
                                "id": "wamid.OUT2",
                                "status": "failed",
                                "recipient_id": "971500000001",
                                "errors": [{"code": 131047, "title": "Re-engagement message"}],
                            }
                        ],
                    },
                }
            )
        )
        assert parsed.statuses[0].status == "failed"
        assert "Re-engagement" in parsed.statuses[0].error

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"entry": None},
            {"entry": [{"changes": "not-a-list"}]},
            {"entry": [{"changes": [{"value": None}]}]},
            {"entry": [{"changes": [{"field": "account_update", "value": {"event": "VERIFIED"}}]}]},
            {"entry": [{"changes": [{"value": {"messages": ["not-an-object"]}}]}]},
        ],
    )
    def test_an_unfamiliar_payload_is_skipped_not_raised(self, payload: dict) -> None:
        # A 500 here is a retry, and a retry is a duplicate message to a real
        # person — then Meta throttles the subscription. Meta ships new event
        # types without notice, so tolerance is a correctness property.
        parsed = parse_webhook(payload)
        assert parsed.messages == []
        assert parsed.statuses == []


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[dict] = []

    async def post(self, url, *, json=None, headers=None):  # type: ignore[no-untyped-def]
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._response


@pytest.fixture
def sent(monkeypatch):  # type: ignore[no-untyped-def]
    """Capture the outbound request instead of making it."""

    def _install(response: _FakeResponse) -> _FakeClient:
        client = _FakeClient(response)

        async def _get_client(*args, **kwargs):  # type: ignore[no-untyped-def]
            return client

        monkeypatch.setattr(
            "src.infrastructure.messaging.whatsapp_cloud.get_client", _get_client
        )
        return client

    return _install


class TestSending:
    async def test_it_posts_what_the_graph_api_expects(self, sent) -> None:  # type: ignore[no-untyped-def]
        client = sent(_FakeResponse(200, {"messages": [{"id": "wamid.OUT"}]}))

        ok, message_id, error = await CloudWhatsAppSender().send(
            phone_number_id="100000000000001",
            access_token="tok",
            to_number="+971500000001",
            body="You're booked for Thursday at 10:00 AM.",
            api_version="v21.0",
        )

        assert (ok, message_id, error) == (True, "wamid.OUT", "")
        call = client.calls[0]
        assert call["url"] == (
            "https://graph.facebook.com/v21.0/100000000000001/messages"
        )
        assert call["headers"]["Authorization"] == "Bearer tok"
        # Meta wants bare digits; a leading "+" is rejected.
        assert call["json"]["to"] == "971500000001"
        assert call["json"]["messaging_product"] == "whatsapp"
        assert call["json"]["text"]["preview_url"] is False

    async def test_the_pinned_api_version_is_used(self, sent) -> None:  # type: ignore[no-untyped-def]
        client = sent(_FakeResponse(200, {"messages": [{"id": "x"}]}))
        await CloudWhatsAppSender().send(
            phone_number_id="1",
            access_token="t",
            to_number="971500000001",
            body="hi",
            api_version="v23.0",
        )
        assert "/v23.0/" in client.calls[0]["url"]

    async def test_a_rejected_send_never_reports_success(self, sent) -> None:  # type: ignore[no-untyped-def]
        sent(
            _FakeResponse(
                400,
                {"error": {"message": "Unsupported post request", "code": 100}},
            )
        )
        ok, message_id, error = await CloudWhatsAppSender().send(
            phone_number_id="1", access_token="t", to_number="971500000001", body="hi"
        )
        assert ok is False
        assert message_id == ""
        assert "Unsupported post request" in error
        assert "100" in error

    async def test_the_closed_24_hour_window_is_explained_in_plain_words(
        self, sent
    ) -> None:  # type: ignore[no-untyped-def]
        # The single most common Cloud API failure in production, and the one
        # whose raw message ("Re-engagement message") explains nothing.
        sent(
            _FakeResponse(
                400,
                {"error": {"message": "Re-engagement message", "code": 131047}},
            )
        )
        ok, _, error = await CloudWhatsAppSender().send(
            phone_number_id="1", access_token="t", to_number="971500000001", body="hi"
        )
        assert ok is False
        assert "24-hour" in error
        assert "template" in error

    async def test_an_expired_token_says_to_reconnect(self, sent) -> None:  # type: ignore[no-untyped-def]
        sent(
            _FakeResponse(
                401,
                {"error": {"message": "Error validating access token", "code": 190}},
            )
        )
        ok, _, error = await CloudWhatsAppSender().send(
            phone_number_id="1", access_token="stale", to_number="971500000001", body="hi"
        )
        assert ok is False
        assert "expired" in error.lower()

    async def test_a_send_meta_accepted_survives_a_missing_id(self, sent) -> None:  # type: ignore[no-untyped-def]
        # Losing the id costs delivery receipts for one message. Failing the
        # send over it would cost the message itself, and a broadcast with it.
        sent(_FakeResponse(200, {}))
        ok, message_id, error = await CloudWhatsAppSender().send(
            phone_number_id="1", access_token="t", to_number="971500000001", body="hi"
        )
        assert (ok, message_id, error) == (True, "", "")
