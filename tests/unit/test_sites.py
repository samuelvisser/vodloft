"""A Site is the website a collection or video is on, whichever Source fetches it,
and the same collection is added once per Site."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sources import collection_on_site, site_for, sources_for


@pytest.mark.parametrize(("url", "source", "key", "name"), [
    ("https://www.youtube.com/@channel", "ytdlp", "youtube", "YouTube"),
    ("https://youtu.be/dQw4w9WgXcQ", "ytdlp", "youtube", "YouTube"),
    ("https://music.youtube.com/playlist?list=PL0123456789", "ytdlp", "youtube", "YouTube"),
    ("https://www.twitch.tv/videos/123", "ytdlp", "twitch", "Twitch"),
    ("https://rumble.com/c/someone", "ytdlp", "rumble", "Rumble"),
    ("https://www.example.com/clip.mp4", "ytdlp", "generic:example.com", "example.com"),
    # A Site a Source is made for wins, whichever Source fetches the link.
    ("https://www.dailywire.com/show/a-show", "ytdlp", "dailywire", "The Daily Wire"),
    ("https://www.dailywire.com/show/a-show", "dailywire", "dailywire", "The Daily Wire"),
    ("https://npo.nl/start/serie/a-series", "npo", "npo", "NPO Start"),
])
def test_a_links_site_is_told_without_the_network(url, source, key, name):
    site = site_for(url, source)
    assert (site.key, site.name) == (key, name)


def test_youtube_is_one_site_across_its_domains():
    assert site_for("https://youtu.be/dQw4w9WgXcQ", "ytdlp").domains == ("youtu.be",)
    assert site_for("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "ytdlp").domains == ("youtube.com",)


def test_the_same_collection_is_the_same_pair_whichever_source_fetches_it():
    url = "https://www.dailywire.com/show/the-ben-shapiro-show"
    by_dailywire = collection_on_site(url, "dailywire", "the-ben-shapiro-show")
    by_ytdlp = collection_on_site(url, "ytdlp", "yt-dlp's own id")
    assert by_dailywire == by_ytdlp
    assert by_dailywire[1] == "the-ben-shapiro-show"
    # On a Site no Source is made for, the fetching Source's id is the Site's.
    assert collection_on_site("https://www.youtube.com/channel/UC123", "ytdlp", "UC123")[1] == "UC123"


def test_the_preferred_source_follows_the_site_not_the_domain():
    ordered = [source.id for source in sources_for("https://www.dailywire.com/show/a-show", {"dailywire": "ytdlp"})]
    assert ordered == ["ytdlp", "dailywire"]
    assert [source.id for source in sources_for("https://www.dailywire.com/show/a-show")] == ["dailywire", "ytdlp"]


@pytest.fixture
def session():
    from backend.db.core import Base
    import backend.db.models  # noqa: F401  (registers every table)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _collection(source_key: str, slug: str, url: str):
    from backend.db.models import Collection
    from backend.utils.helpers import generate_uuid

    return Collection(
        uuid=generate_uuid(), slug=slug, title=slug, sharing_url=url, membership_level="FREE", type="series",
        episode_identifier="date_based", author_name="Host", author_slug="host", source_key=source_key,
    )


def test_a_collection_is_added_once_per_site_through_any_source(session):
    from backend.services.sites import CollectionAlreadyAddedError, place_collection

    first = _collection("dailywire", "a-show", "https://www.dailywire.com/show/a-show")
    place_collection(session, first)
    session.add(first)
    session.flush()
    assert (first.site_key, first.site_ref) == ("dailywire", "a-show")
    assert first.site.name == "The Daily Wire"

    again = _collection("ytdlp", "dailywire-a-show", "https://dailywire.com/show/a-show/")
    with pytest.raises(CollectionAlreadyAddedError, match="a-show is already in VODLoft"):
        place_collection(session, again)


def test_the_database_refuses_a_second_copy_of_a_sites_collection(session):
    from backend.services.sites import place_collection

    first = _collection("dailywire", "a-show", "https://www.dailywire.com/show/a-show")
    place_collection(session, first)
    session.add(first)
    session.flush()

    second = _collection("ytdlp", "other-slug", "https://dailywire.com/show/a-show")
    second.site_key, second.site_ref = "dailywire", "a-show"
    session.add(second)
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_site_remembers_every_domain_it_was_seen_on(session):
    from backend.db.models import Video
    from backend.services.sites import place_video
    from backend.utils.helpers import generate_uuid

    for slug, url in (("a", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"), ("b", "https://youtu.be/dQw4w9WgXcQ")):
        video = Video(uuid=generate_uuid(), type="video", source_key="ytdlp", slug=slug, sharing_url=url, title=slug, duration=0)
        place_video(session, video)
        session.add(video)
        session.flush()
        assert video.site_key == "youtube"
    assert video.site.domains == ["youtube.com", "youtu.be"]
