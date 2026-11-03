from fastapi import APIRouter

from backend.api.models.onboarding import OnboardingStatusAPIRead
from backend.app import db_session

from .service import complete_onboarding, get_onboarding_status, start_fresh, undo_start_fresh
from backend.security.access import Area, Level
from backend.security.deps import requires, signed_in


router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


@router.get("/status", dependencies=[signed_in()], response_model=OnboardingStatusAPIRead)
def onboarding_status():
    """Return whether the one-time first-run experience has been completed."""
    with db_session() as s:
        try:
            result = get_onboarding_status(s)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.post("/complete", dependencies=[requires(Area.SETTINGS, Level.MANAGE)], response_model=OnboardingStatusAPIRead)
def onboarding_complete():
    """Permanently mark the first-run experience as complete."""
    with db_session() as s:
        try:
            result = complete_onboarding(s)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.post("/start-fresh", dependencies=[requires(Area.SETTINGS, Level.MANAGE)], status_code=204)
def onboarding_start_fresh():
    """Add the default Collection profiles, once a library started from scratch first needs one."""
    with db_session() as s:
        try:
            start_fresh(s)
            s.commit()
        except Exception:
            s.rollback()
            raise


@router.delete("/start-fresh", dependencies=[requires(Area.SETTINGS, Level.MANAGE)], status_code=204)
def onboarding_undo_start_fresh():
    """Remove the default Collection profiles again, when the person goes back to choose an import instead."""
    with db_session() as s:
        try:
            undo_start_fresh(s)
            s.commit()
        except Exception:
            s.rollback()
            raise
