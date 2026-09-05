"""How far a workspace has got, and what that entitles it to see.

The navigation used to show every one of its twenty-odd destinations from the
first second of the first session. Someone who signed up to build a voice
assistant landed on a rail whose first group was Appointments, and had no way
to tell which of Locations, Availability, Broadcast or Call Logs they were
supposed to touch first. The answer is that they were supposed to touch none of
them — they all describe an assistant that does not exist yet.

So the shell reveals itself in step with the workspace. `Stage` is that
progression, and it is derived from data the tenant already has rather than
from a flag someone remembered to set:

    build    nothing configured yet          → build the assistant
    teach    an assistant exists             → give it knowledge
    test     it has something to answer from → try it
    launch   it has been tried               → put it on a channel
    operate  it is live                      → run it: bookings, campaigns, logs

Two properties matter more than the ladder itself.

*Derived, not stored.* Every milestone is a question about rows that already
exist. A workspace that has been running for a year answers `operate` on its
first load after this ships, with no backfill and nothing hidden from it.

*Highest reached, not first unmet.* `stage_for` returns the furthest stage
whose condition holds, not the first one that fails. Someone who published an
assistant without ever uploading a document is at `operate`, not stuck at
`teach` — skipping a step is a choice, not a reason to take their menu away.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from src.domain.shared.identifiers import TenantId, UserId

Stage = Literal["build", "teach", "test", "launch", "operate"]

# Ascending. Index into this is the ordering used everywhere, including by the
# frontend's `stages.ts` — the two lists must stay in the same order.
STAGE_ORDER: tuple[Stage, ...] = ("build", "teach", "test", "launch", "operate")

NavMode = Literal["guided", "full"]


@dataclass(frozen=True)
class Milestones:
    """The seven yes/no questions the whole progression is built on."""

    # A chatbot exists that isn't the untouched one signup created. See
    # `provisioning.py`: every tenant is born with a "Default Assistant", so
    # "has a chatbot" is true one millisecond after signup and answers nothing.
    assistant_configured: bool = False
    # At least one document finished ingesting. A document still processing
    # doesn't count — the assistant cannot answer from it yet.
    knowledge_ready: bool = False
    # Somebody has opened Test and started a session against a bot.
    assistant_tested: bool = False
    # A phone number or WhatsApp number is linked.
    channel_connected: bool = False
    # An assistant is published (`is_public`).
    assistant_live: bool = False
    # Locations/services/hours are complete enough that booking can return a
    # slot — the same check `/appointments/readiness` runs.
    appointments_ready: bool = False
    integrations_connected: bool = False


def stage_for(m: Milestones) -> Stage:
    """The furthest stage this workspace has reached.

    `appointments_ready` and `integrations_connected` promote to `operate` on
    their own even without a live assistant. They are not part of the intended
    path — they are the footprint of a workspace that was already using those
    surfaces before staged navigation existed, and the one thing this must
    never do is take a page away from someone who is mid-workflow in it.
    """
    if m.assistant_live or m.appointments_ready or m.integrations_connected:
        return "operate"
    if m.assistant_tested or m.channel_connected:
        return "launch"
    if m.knowledge_ready:
        return "test"
    if m.assistant_configured:
        return "teach"
    return "build"


def stage_index(stage: Stage) -> int:
    return STAGE_ORDER.index(stage)


def at_least(stage: Stage, required: Stage) -> bool:
    return stage_index(stage) >= stage_index(required)


@dataclass
class OnboardingPrefs:
    """What this person has already been shown. One row per user."""

    user_id: UserId
    tenant_id: TenantId
    nav_mode: NavMode = "guided"
    tours_completed: list[str] = field(default_factory=list)
    dismissed: list[str] = field(default_factory=list)
    celebrated_stages: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def with_marked(self, field_name: str, value: str) -> OnboardingPrefs:
        """Append `value` to one of the three list fields, idempotently."""
        current: list[str] = list(getattr(self, field_name))
        if value not in current:
            current.append(value)
        setattr(self, field_name, current)
        self.updated_at = datetime.now(UTC)
        return self


# --- The next thing to do ----------------------------------------------------
#
# One action, never a menu. The setup checklist can show the whole ladder; this
# is what the sidebar card and the empty states say, and there is exactly one
# right answer at any moment.


@dataclass(frozen=True)
class NextStep:
    key: str
    title: str
    body: str
    href: str
    cta: str
    # Which per-area tour "Show me" should replay, if any.
    tour: str | None = None


_NEXT_STEPS: dict[Stage, NextStep] = {
    "build": NextStep(
        key="create-assistant",
        title="Build your voice AI assistant",
        body="Describe what it should do in plain English — Evara AI writes the "
        "conversation for you.",
        href="/assistants",
        cta="Create assistant",
        tour="assistants",
    ),
    "teach": NextStep(
        key="add-knowledge",
        title="Give it something to answer from",
        body="Upload your FAQs, price list, policies — anything a caller might ask about.",
        href="/knowledge",
        cta="Add knowledge",
        tour="knowledge",
    ),
    "test": NextStep(
        key="test-assistant",
        title="Talk to your assistant",
        body="Open it and hit Test — by chat or by voice — before a real caller does.",
        href="/assistants",
        cta="Test it",
        tour=None,
    ),
    "launch": NextStep(
        key="connect-channel",
        title="Put it where your customers are",
        body="Connect a phone number or WhatsApp, then publish. That's when it goes live.",
        href="/channels",
        cta="Choose a channel",
        tour="channels",
    ),
    "operate": NextStep(
        key="setup-appointments",
        title="Let it book appointments",
        body="Add your locations, services and opening hours — no external calendar needed.",
        href="/appointments/services",
        cta="Set up booking",
        tour="appointments",
    ),
}


def next_step_for(stage: Stage, m: Milestones) -> NextStep | None:
    """What to put in front of this workspace right now.

    At `operate` the ladder is finished, so the card switches to the largest
    thing still unconfigured — and disappears entirely once nothing is left,
    rather than nagging a workspace that is fully set up.
    """
    if stage != "operate":
        return _NEXT_STEPS[stage]
    if not m.appointments_ready:
        return _NEXT_STEPS["operate"]
    if not m.integrations_connected:
        return NextStep(
            key="connect-tools",
            title="Connect your other tools",
            body="Link a CRM, Sheets or your calendar so the assistant can act, not just answer.",
            href="/integrations",
            cta="Browse integrations",
            tour="integrations",
        )
    return None
