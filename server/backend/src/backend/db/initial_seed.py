"""First-install library defaults; migrations own existing-install changes."""
from sqlalchemy import select
from backend.db.core import get_session, load_database_models
from backend.db.models.local_media_profile import DomainLocalMediaProfile
from backend.db.models.vodloft import Domain


def _seed_local_media_profiles(session):
    for hostname, label in (("dailywire.com", "The Daily Wire"), ("youtube.com", "YouTube")):
        domain = session.scalar(select(Domain).where(Domain.hostname == hostname))
        if not domain:
            domain = Domain(hostname=hostname, display_name=label)
            session.add(domain)
            session.flush()
        for suffix, preferred in (("video", "format_1080p"), ("audio", "format_audio_only")):
            slug = f"{hostname}-{suffix}"
            if not session.scalar(select(DomainLocalMediaProfile.id).where(DomainLocalMediaProfile.slug == slug)):
                session.add(DomainLocalMediaProfile(name=f"{label} {suffix.title()}", slug=slug,
                    domain_id=domain.id, preferred_format=preferred,
                    output_template="/downloads/{{ domain }}/{{ collection or media_type }}/{{ title }} - {{ id }}.ext",
                    applicable_kinds=["video", "movie", "movie_extra"], enabled=True,
                    representation={"container": "m4a" if suffix == "audio" else "mp4"}, delivery_target_ids=[]))


def seed_initial_database():
    load_database_models()
    with get_session() as session:
        _seed_local_media_profiles(session)
        session.commit()
