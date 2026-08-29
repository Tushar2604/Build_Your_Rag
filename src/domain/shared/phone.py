"""One shape for a phone number, everywhere it is used as an identity.

A WhatsApp contact reaches this system through four writers — the bridge's live
socket, the bridge's history import, a Twilio webhook, and a pasted campaign
list — and each of them had its own idea of what a phone number looks like:
`+919220910108`, `919220910108`, `whatsapp:+919220910108`, `+91 92209 10108`.

`whatsapp_conversations` is unique on `(owner, phone_number)`, and every one of
those strings is a different value. The same person therefore got a new thread,
a new chat history and a new row in Candidates for each shape they happened to
arrive in — which is exactly the "one number, three profiles" this module
exists to stop.

Deliberately separate from `broadcast.normalize_phone`, and deliberately
total. That one validates a number a human typed, and returns None when it
cannot be trusted — correct, because a wrong guess messages a stranger. This
one is an identity function for a number we have already been given by
WhatsApp: it must return *something* for every input, because refusing to
canonicalise here would mean dropping a real message.
"""

from __future__ import annotations

import re

# Anything that is not a digit tells us nothing about which handset this is.
# Separators, the `whatsapp:` scheme, a JID's `@s.whatsapp.net` suffix and a
# multi-device `:12` resource are all noise around the same number.
_NON_DIGITS = re.compile(r"\D")

# Below this a "number" is a fragment, a extension, or something that was never
# a phone number — canonicalising it would merge unrelated threads together,
# which is far worse than leaving a scrap alone.
_MIN_DIGITS = 6
_MAX_DIGITS = 15


def phone_digits(raw: str) -> str:
    """Just the digits, or "" when there aren't plausibly enough of them.

    The comparison key. Two numbers are the same handset when these match, and
    never when the raw strings do — `"+971 50 123 4567"` and `"971501234567"`
    are one phone written twice.
    """
    if not raw:
        return ""
    text = str(raw).strip()
    # Order matters. `whatsapp:` is a scheme in front of the number, while a
    # JID's `:12` is a multi-device resource behind it — stripping "everything
    # after a colon" would eat the number in the first case, and "everything
    # before" would eat it in the second.
    if ":" in text and not text.split(":", 1)[0].isdigit():
        text = text.split(":", 1)[1]
    # A JID carries the number before the `@`; the rest is routing.
    text = text.split("@")[0].split(":")[0]
    digits = _NON_DIGITS.sub("", text)
    if not (_MIN_DIGITS <= len(digits) <= _MAX_DIGITS):
        return ""
    return digits


def canonical_phone(raw: str) -> str:
    """The one form this system stores: `+` followed by digits.

    Chosen because it is what the bridge already emits and what E.164 asks for,
    so the overwhelming majority of existing rows are already correct and the
    backfill has little to do.

    Input it cannot make sense of is returned trimmed rather than blanked — a
    thread keyed by something odd is still a thread somebody may need to read,
    and losing its key would orphan it.
    """
    digits = phone_digits(raw)
    if not digits:
        return (raw or "").strip()
    return f"+{digits}"


def same_phone(a: str, b: str) -> bool:
    """Are these the same handset? Falls back to exact match for inputs that
    have no usable digits, so two equally odd keys still compare equal."""
    da, db = phone_digits(a), phone_digits(b)
    if da and db:
        return da == db
    return (a or "").strip() == (b or "").strip()
