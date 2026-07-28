"""Twilio webhook request validation — reimplemented from Twilio's documented
algorithm (https://www.twilio.com/docs/usage/webhooks/webhooks-security) using
only the standard library, so this integration needs no Twilio SDK dependency.

Algorithm: HMAC-SHA1 of the request URL with each POST param's key+value
(sorted by key, concatenated with no delimiter) appended, keyed by the
account's Auth Token, then base64-encoded — compared to the
`X-Twilio-Signature` header.
"""

from __future__ import annotations

import base64
import hashlib
import hmac


def compute_twilio_signature(url: str, params: dict[str, str], auth_token: str) -> str:
    data = url
    for key in sorted(params.keys()):
        data += key + params[key]
    digest = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def verify_twilio_signature(
    url: str, params: dict[str, str], signature: str, auth_token: str
) -> bool:
    """Constant-time comparison — never use `==` on secrets/signatures."""
    if not signature:
        return False
    expected = compute_twilio_signature(url, params, auth_token)
    return hmac.compare_digest(expected, signature)
