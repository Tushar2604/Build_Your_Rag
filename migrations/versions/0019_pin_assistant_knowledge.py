"""Pin each assistant's knowledge base to an explicit document set

`chatbots.allowed_document_ids = []` used to mean "search every document in the
tenant". It now means what it says: this assistant has no knowledge base and
answers from its Conversational Flow alone. Each assistant owns its own sources
rather than inheriting whatever another assistant happened to upload.

Left alone, that change would silently strip the knowledge from every assistant
built under the old rule — they would keep answering, just without their
documents, which is the worst kind of regression because nothing errors. So this
pins the set those assistants were *actually* retrieving from at the moment of
the upgrade: every ready document in their own tenant.

Only rows with an empty list are touched; an assistant already scoped to
specific documents is already explicit and is left exactly as it is.

Revision ID: 0019_pin_assistant_knowledge
Revises: 0018_oauth_connections
Create Date: 2026-08-10
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019_pin_assistant_knowledge"
down_revision: str | None = "0018_oauth_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # jsonb_agg returns NULL for an empty match, hence the COALESCE — otherwise
    # a tenant with no ready documents would get NULL instead of [] and the
    # mapper would read it back as "unset".
    op.execute(
        """
        UPDATE chatbots c
        SET allowed_document_ids = COALESCE(
            (
                SELECT jsonb_agg(d.id::text)
                FROM documents d
                WHERE d.tenant_id = c.tenant_id AND d.status = 'ready'
            ),
            '[]'::jsonb
        )
        WHERE c.allowed_document_ids = '[]'::jsonb
        """
    )


def downgrade() -> None:
    # Not reversible: once pinned, an explicit set is indistinguishable from one
    # the owner chose deliberately, and clearing every list would delete real
    # configuration. The old "empty means everything" reading is restored by
    # reverting the code, not the data.
    pass
