from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.models.onboarding import OnboardingStatusAPIRead
from backend.db.initial_seed import remove_fresh_start_profiles, seed_fresh_start_profiles
from backend.db.models import Collection, ImportRun, Settings
from config import get_settings


def _get_or_create_settings(s: Session) -> Settings:
    settings = s.query(Settings).order_by(Settings.id).first()
    if settings is None:
        settings = Settings(onboarding_completed=False)
        s.add(settings)
        s.flush()
    return settings


def _as_response(settings: Settings) -> OnboardingStatusAPIRead:
    return OnboardingStatusAPIRead(
        completed=settings.onboarding_completed,
        admin_password_configured=get_settings().admin_auth.enabled,
    )


def get_onboarding_status(s: Session) -> OnboardingStatusAPIRead:
    """Read-only: every page asks for this, so it must never wait for the writer's turn."""
    settings = s.query(Settings).order_by(Settings.id).first()
    return _as_response(settings or Settings(onboarding_completed=False))


def start_fresh(s: Session) -> None:
    """The person started a fresh library and now needs a Collection profile: add the default ones."""
    seed_fresh_start_profiles(s)
    s.flush()


def undo_start_fresh(s: Session) -> None:
    """The person went back to choose between starting fresh and importing: remove the default
    Collection profiles again, so an import starts without them. Nothing changes once onboarding is
    complete or a collection uses a profile."""
    if _get_or_create_settings(s).onboarding_completed or s.scalar(select(Collection.id).limit(1)) is not None:
        return
    remove_fresh_start_profiles(s)
    s.flush()


def complete_onboarding(s: Session) -> OnboardingStatusAPIRead:
    settings = _get_or_create_settings(s)
    if not settings.onboarding_completed and s.scalar(
        select(ImportRun.id).where(ImportRun.status.in_(("running", "waiting", "finished"))).limit(1)
    ) is None:
        seed_fresh_start_profiles(s)
    settings.onboarding_completed = True
    s.flush()
    return _as_response(settings)
