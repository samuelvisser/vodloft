from fastapi import APIRouter

from backend.api.models.onboarding import OnboardingStatusAPIRead

from .service import complete_onboarding, get_onboarding_status, start_fresh, undo_start_fresh
from backend.security.access import Area, Level
from backend.security.deps import requires, signed_in
from backend.db.core import run_write_transaction


router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


@router.get("/status", dependencies=[signed_in()], response_model=OnboardingStatusAPIRead)
def onboarding_status():
    """Return whether the one-time first-run experience has been completed."""
    def work(s):
        return get_onboarding_status(s)

    return run_write_transaction(work)


@router.post("/complete", dependencies=[requires(Area.SETTINGS, Level.MANAGE)], response_model=OnboardingStatusAPIRead)
def onboarding_complete():
    """Permanently mark the first-run experience as complete."""
    def work(s):
        return complete_onboarding(s)

    return run_write_transaction(work)


@router.post("/start-fresh", dependencies=[requires(Area.SETTINGS, Level.MANAGE)], status_code=204)
def onboarding_start_fresh():
    """Add the default Collection profiles, once a library started from scratch first needs one."""
    def work(s):
        start_fresh(s)

    run_write_transaction(work)


@router.delete("/start-fresh", dependencies=[requires(Area.SETTINGS, Level.MANAGE)], status_code=204)
def onboarding_undo_start_fresh():
    """Remove the default Collection profiles again, when the person goes back to choose an import instead."""
    def work(s):
        undo_start_fresh(s)

    run_write_transaction(work)
