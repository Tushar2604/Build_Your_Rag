"""Guard: the bridge-event webhook must reject anything without the shared secret.

This endpoint takes a session id and a message and turns it into an assistant
reply sent to a real person's WhatsApp. It carries no JWT — the bridge acts for
no particular user — so the token check is the *only* thing standing between the
open internet and someone driving a stranger's linked account.

The token check runs before any database access, which is what lets these run
without a Postgres.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from src.interfaces.api.app import create_app

ENDPOINT = "/api/v1/whatsapp-web/bridge-events"


def _payload(event: str = "message") -> dict:
    return {
        "session_id": str(uuid.uuid4()),
        "event": event,
        "from": "+917502163963",
        "jid": "917502163963@s.whatsapp.net",
        "text": "hello",
    }


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_no_token_is_rejected(client: TestClient) -> None:
    assert client.post(ENDPOINT, json=_payload()).status_code == 403


def test_wrong_token_is_rejected(client: TestClient) -> None:
    resp = client.post(ENDPOINT, json=_payload(), headers={"X-Bridge-Token": "guessed"})
    assert resp.status_code == 403


def test_empty_token_header_is_rejected(client: TestClient) -> None:
    resp = client.post(ENDPOINT, json=_payload(), headers={"X-Bridge-Token": ""})
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "event", ["qr", "linked", "disconnected", "logged_out", "failed", "message"]
)
def test_every_event_type_needs_the_token(client: TestClient, event: str) -> None:
    assert client.post(ENDPOINT, json=_payload(event)).status_code == 403


def test_an_unconfigured_server_rejects_even_a_matching_empty_token(
    client: TestClient,
) -> None:
    # With BRIDGE_TOKEN unset, "" must not authenticate by matching the unset
    # value — otherwise a deploy that forgot the secret is wide open.
    resp = client.post(ENDPOINT, json=_payload(), headers={"X-Bridge-Token": ""})
    assert resp.status_code == 403


def test_the_endpoint_is_hidden_from_the_public_schema() -> None:
    # It's machine-to-machine; publishing it in /docs invites probing.
    assert ENDPOINT not in create_app().openapi()["paths"]


def test_malformed_body_still_does_not_leak_past_the_token_check(
    client: TestClient,
) -> None:
    # Auth must be evaluated before anything reads the payload.
    assert client.post(ENDPOINT, json={"nonsense": True}).status_code in (403, 422)
