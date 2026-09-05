"""The staged shell must never take a page away from someone using it.

`stage_for` decides how much of the navigation a workspace can see. Getting it
wrong in the generous direction shows a new user a menu they can't use yet;
getting it wrong in the strict direction hides Appointments from a clinic that
books through it every day. These tests pin the second direction hardest.
"""

from __future__ import annotations

from src.domain.onboarding.entities import (
    Milestones,
    NextStep,
    at_least,
    next_step_for,
    stage_for,
)


def test_a_brand_new_workspace_starts_at_build() -> None:
    # Every tenant is born with an untouched "Default Assistant", so this is
    # the state one second after signup — not an empty database.
    assert stage_for(Milestones()) == "build"


def test_configuring_an_assistant_unlocks_the_next_rung() -> None:
    assert stage_for(Milestones(assistant_configured=True)) == "teach"


def test_ready_knowledge_reaches_test() -> None:
    assert stage_for(Milestones(assistant_configured=True, knowledge_ready=True)) == "test"


def test_testing_reaches_launch() -> None:
    m = Milestones(assistant_configured=True, knowledge_ready=True, assistant_tested=True)
    assert stage_for(m) == "launch"


def test_going_live_reaches_operate() -> None:
    m = Milestones(assistant_configured=True, assistant_live=True)
    assert stage_for(m) == "operate"


def test_a_skipped_step_does_not_hold_the_workspace_back() -> None:
    """Published without ever uploading a document, which is a legitimate way
    to use the product. The old first-unmet-step reading would have pinned this
    workspace at `teach` and hidden the operations pages from a live assistant."""
    m = Milestones(assistant_configured=True, assistant_live=True, knowledge_ready=False)
    assert stage_for(m) == "operate"


def test_an_existing_workspace_using_appointments_is_never_demoted() -> None:
    """The safety net for everyone who predates staged navigation.

    This tenant has booking fully configured and no live assistant — nothing on
    the intended path is true for it. It still gets the whole shell, because
    the alternative is a clinic opening the app to find its calendar gone.
    """
    assert stage_for(Milestones(appointments_ready=True)) == "operate"


def test_a_connected_integration_is_the_same_kind_of_evidence() -> None:
    assert stage_for(Milestones(integrations_connected=True)) == "operate"


def test_a_connected_channel_counts_as_reaching_launch() -> None:
    """Linking WhatsApp is proof of intent even if nobody pressed Test."""
    assert stage_for(Milestones(assistant_configured=True, channel_connected=True)) == "launch"


def test_at_least_compares_stages_in_order() -> None:
    assert at_least("operate", "build")
    assert at_least("test", "test")
    assert not at_least("teach", "launch")


def test_the_next_step_is_always_the_current_rung() -> None:
    step = next_step_for("build", Milestones())
    assert isinstance(step, NextStep)
    assert step.href == "/assistants"


def test_a_live_workspace_is_pointed_at_booking_then_integrations() -> None:
    live = Milestones(assistant_configured=True, assistant_live=True)
    assert next_step_for("operate", live).href == "/appointments/services"

    booking_done = Milestones(
        assistant_configured=True, assistant_live=True, appointments_ready=True
    )
    assert next_step_for("operate", booking_done).href == "/integrations"


def test_a_fully_configured_workspace_is_left_alone() -> None:
    """No card, no nag. Finishing setup has to actually end."""
    done = Milestones(
        assistant_configured=True,
        knowledge_ready=True,
        assistant_tested=True,
        channel_connected=True,
        assistant_live=True,
        appointments_ready=True,
        integrations_connected=True,
    )
    assert next_step_for("operate", done) is None
