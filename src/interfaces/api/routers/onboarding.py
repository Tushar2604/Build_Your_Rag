"""What the shell is allowed to show this person yet.

One GET that answers the whole question — how far the workspace has got, what
the single next action is, and which cards this particular user has already
closed — and one PATCH for the three things a person can change about it.

Why it is a server call at all: the previous version of this lived entirely in
one localStorage key, which meant the answer was per-browser. Signing in on a
second machine replayed the welcome screen at someone who had finished setting
up months earlier, and a workspace that predated onboarding had no state at all
and so could never be shown the parts of the product it had not touched. Both
of those are the same bug — progress is a fact about the workspace's data, and
the workspace's data lives here.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.application.use_cases.booking_readiness import compute_booking_readiness
from src.config.settings import get_settings
from src.domain.onboarding.entities import (
    Milestones,
    OnboardingPrefs,
    next_step_for,
    stage_for,
)
from src.interfaces.api.deps import ContainerDep, PrincipalDep
from src.interfaces.api.schemas import (
    MilestonesSchema,
    NextStepSchema,
    OnboardingPrefsUpdate,
    OnboardingStateResponse,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _default_prefs(principal) -> OnboardingPrefs:  # noqa: ANN001
    """A user with no row yet. Never written — a row appears on first PATCH."""
    return OnboardingPrefs(user_id=principal.user_id, tenant_id=principal.tenant_id)


async def _state(principal, container) -> OnboardingStateResponse:  # noqa: ANN001
    settings = get_settings()
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        milestones = await uow.onboarding.milestones(principal.tenant_id)
        # Booking readiness is a computation rather than a row check, so the
        # read model leaves it unset and it is filled in here. Skipped
        # entirely when scheduling is flagged off — there is no Appointments
        # group to unlock, and the four collection reads would be wasted.
        if settings.appointments_enabled:
            readiness = await compute_booking_readiness(uow, principal.tenant_id)
            milestones = Milestones(
                **{**milestones.__dict__, "appointments_ready": readiness.ready}
            )
        prefs = (
            await uow.onboarding.get_prefs(principal.tenant_id, principal.user_id)
            if principal.user_id
            else None
        ) or _default_prefs(principal)

    stage = stage_for(milestones)
    step = next_step_for(stage, milestones)
    return OnboardingStateResponse(
        stage=stage,
        milestones=MilestonesSchema(**milestones.__dict__),
        next_step=NextStepSchema(**step.__dict__) if step else None,
        nav_mode=prefs.nav_mode,
        tours_completed=prefs.tours_completed,
        dismissed=prefs.dismissed,
        celebrated_stages=prefs.celebrated_stages,
    )


@router.get("/state", response_model=OnboardingStateResponse)
async def get_state(
    principal: PrincipalDep, container: ContainerDep
) -> OnboardingStateResponse:
    return await _state(principal, container)


@router.patch("/state", response_model=OnboardingStateResponse)
async def update_state(
    body: OnboardingPrefsUpdate, principal: PrincipalDep, container: ContainerDep
) -> OnboardingStateResponse:
    """Record a dismissal, a finished tour, a celebrated unlock, or the nav mode.

    Returns the full recomputed state rather than an ack, so a client that
    dismisses a card never has to follow up with a GET to find out what the
    shell should look like now.
    """
    # API-key callers have no user, and preferences are per-user. Reading the
    # state still works for them; there is simply nothing to write it against.
    if principal.user_id is not None:
        async with container.unit_of_work() as uow:
            uow.set_tenant_scope(principal.tenant_id)
            prefs = await uow.onboarding.get_prefs(
                principal.tenant_id, principal.user_id
            ) or _default_prefs(principal)

            if body.reset:
                # Deliberately does not touch nav_mode: "start the guidance
                # over" and "I want the full menu" are unrelated choices, and
                # silently re-hiding someone's navigation would be a nasty
                # surprise from a button labelled "replay the walkthrough".
                prefs.dismissed = []
                prefs.tours_completed = []
                prefs.celebrated_stages = []
            if body.nav_mode is not None:
                prefs.nav_mode = body.nav_mode
            if body.complete_tour:
                prefs.with_marked("tours_completed", body.complete_tour)
            if body.dismiss:
                prefs.with_marked("dismissed", body.dismiss)
            if body.celebrate_stage:
                prefs.with_marked("celebrated_stages", body.celebrate_stage)

            await uow.onboarding.save_prefs(prefs)
            await uow.commit()

    return await _state(principal, container)
