"""The Sources the Library has media from, which decide whether items say which Source they come from."""
from __future__ import annotations

from test_ytdlp_collections import session  # noqa: F401


def test_sources_in_use_come_from_collections_and_creators(session):
    from backend.api.endpoints.sources.service import sources_in_use
    from backend.db.models import Collection, Creator, CreatorAccount

    assert sources_in_use(session) == []

    for source_key, slug in (("ytdlp", "workshop"), ("ytdlp", "workshop-shorts")):
        session.add(Collection(
            uuid=f"uuid-{slug}", slug=slug, source_key=source_key, title=slug, sharing_url=f"https://www.youtube.com/@{slug}",
            membership_level="FREE", type="series", episode_identifier="seasonal", author_name="x", author_slug="x",
        ))
    session.commit()
    assert sources_in_use(session) == ["ytdlp"]

    creator = Creator(uuid="c", slug="ben", title="Ben Shapiro")
    creator.accounts.append(CreatorAccount(
        source_key="dailywire", site_key="dailywire", site_ref="ben-shapiro", url="https://www.dailywire.com/author/ben",
    ))
    session.add(creator)
    session.commit()

    assert sources_in_use(session) == ["dailywire", "ytdlp"]
