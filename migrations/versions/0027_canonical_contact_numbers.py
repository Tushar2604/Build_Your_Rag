"""One row per contact: canonicalise stored WhatsApp numbers

The reported symptom was a contact appearing three times in Candidates with the
same name and the same phone number, each copy holding a different slice of the
conversation.

`whatsapp_conversations` is unique on `(whatsapp_channel_id, phone_number)`, and
four writers each spelled a number their own way — the bridge's live socket
(`+919220910108`), its history import, a Twilio webhook (`whatsapp:+91...`) and
a pasted campaign list (`+91 92209 10108`). Every spelling was a different key,
so the same person got a fresh thread, a fresh chat history and a fresh
Candidates row for each one.

The writers now canonicalise (`src/domain/shared/phone.py`). This rewrites what
they already stored, in two steps:

  1. Rewrite every `phone_number` to `+<digits>`, but ONLY where that does not
     collide with a row that already holds the canonical form. Collisions are
     genuine duplicates and are left alone here — merging them means moving
     messages between chat sessions, which is application logic with rules
     about which copy wins, and belongs in `merge_duplicate_threads` rather
     than in a migration that cannot be reviewed against those rules.
  2. Nothing else. The duplicates that remain are folded together by the
     Channels/Candidates pages calling `POST /whatsapp-web/sessions/merge-
     duplicates`, which re-points the messages and keeps the older thread.

Deliberately conservative about what counts as a number: 6-15 digits, matching
`phone_digits`. A row whose key was never a phone number keeps it, because
blanking it would orphan a thread somebody may still need to read.

Revision ID: 0027_canonical_contact_numbers
Revises: 0026_whatsapp_crm_inbox
Create Date: 2026-08-29
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027_canonical_contact_numbers"
down_revision: str | None = "0026_whatsapp_crm_inbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# `regexp_replace(..., 'g')` is the same reduction `phone_digits` performs in
# Python. Kept as a CTE so the length guard and the collision check both read
# from one definition of "the digits".
_CANONICALISE = """
WITH candidate AS (
    SELECT
        id,
        whatsapp_channel_id,
        '+' || regexp_replace(phone_number, '[^0-9]', '', 'g') AS canonical
    FROM whatsapp_conversations
    WHERE length(regexp_replace(phone_number, '[^0-9]', '', 'g')) BETWEEN 6 AND 15
      AND phone_number <> '+' || regexp_replace(phone_number, '[^0-9]', '', 'g')
)
UPDATE whatsapp_conversations AS c
SET phone_number = candidate.canonical
FROM candidate
WHERE c.id = candidate.id
  -- Skip rows whose canonical form is already taken on the same number. Those
  -- are real duplicates; merging them moves messages between chat sessions and
  -- is done by the application, which knows which copy wins.
  AND NOT EXISTS (
      SELECT 1
      FROM whatsapp_conversations AS other
      WHERE other.whatsapp_channel_id = candidate.whatsapp_channel_id
        AND other.phone_number = candidate.canonical
        AND other.id <> candidate.id
  )
"""


def upgrade() -> None:
    op.execute(_CANONICALISE)


def downgrade() -> None:
    # Irreversible by design: the original spellings are exactly the
    # information this migration exists to discard, and there is nowhere they
    # were kept. Reverting the code is enough — canonical numbers are valid
    # input to every reader, old and new.
    pass
