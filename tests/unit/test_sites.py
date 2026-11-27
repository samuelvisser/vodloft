"""A Site is the website a collection or video is on, whichever Source fetches it,
and the same collection is added once per Site."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sources import SiteSetting, StreamMethod, UpgradeImprovement, collection_on_site, site_for, source_site, sources_for


@pytest.mark.parametrize(("url", "source", "key", "name"), [
    ("https://www.youtube.com/@channel", "ytdlp", "youtube", "YouTube"),
    ("https://youtu.be/dQw4w9WgXcQ", "ytdlp", "youtube", "YouTube"),
    ("https://music.youtube.com/playlist?list=PL0123456789", "ytdlp", "youtube", "YouTube"),
    ("https://www.twitch.tv/videos/123", "ytdlp", "twitch", "Twitch"),
    ("https://rumble.com/c/someone", "ytdlp", "rumble", "Rumble"),
    ("https://www.example.com/clip.mp4", "ytdlp", "generic:example.com", "example.com"),
    # A site's home page, which only yt-dlp's generic extractor handles, is still on the site whose domain it is.
    ("https://instagram.com", "ytdlp", "instagram", "Instagram"),
    ("https://www.twitch.tv/", "ytdlp", "twitch", "Twitch"),
    ("https://x.com", "ytdlp", "twitter", "X"),
    ("https://notinstagram.com", "ytdlp", "generic:notinstagram.com", "notinstagram.com"),
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


def test_what_a_site_offers_comes_from_the_source_that_fetches_it():
    url = "https://www.dailywire.com/show/the-ben-shapiro-show"
    by_dailywire, by_ytdlp = source_site(url, "dailywire"), source_site(url, "ytdlp")
    # Both are The Daily Wire, so a user's settings for the Site apply to both.
    assert (by_dailywire.key, by_dailywire.name) == (by_ytdlp.key, by_ytdlp.name) == ("dailywire", "The Daily Wire")

    assert by_dailywire.settings.offers(SiteSetting.DOWNLOAD_WITH_COUNTDOWN)
    assert by_dailywire.upgrade_checks.improvements == (UpgradeImprovement.LENGTH,)
    assert by_dailywire.settings.presets[SiteSetting.UPGRADE_CHECK] is True
    assert StreamMethod.HLS in by_dailywire.stream_methods

    # yt-dlp has no contract for The Daily Wire, so it offers what it offers any site.
    assert not by_ytdlp.settings.offers(SiteSetting.DOWNLOAD_WITH_COUNTDOWN)
    assert by_ytdlp.upgrade_checks.improvements[-1] is UpgradeImprovement.LENGTH
    assert not by_ytdlp.streams
    assert by_ytdlp.upgrade_checks == source_site("https://www.example.com/clip.mp4", "ytdlp").upgrade_checks


def test_only_youtube_offers_sponsorblock_as_a_better_version():
    youtube = source_site("https://www.youtube.com/@channel", "ytdlp").upgrade_checks
    assert youtube.improvements == (
        UpgradeImprovement.RESOLUTION, UpgradeImprovement.SPONSORBLOCK, UpgradeImprovement.SUBTITLES, UpgradeImprovement.CODEC,
        UpgradeImprovement.LENGTH,
    )
    assert UpgradeImprovement.SPONSORBLOCK not in source_site("https://rumble.com/c/someone", "ytdlp").upgrade_checks.improvements


def test_every_site_offers_a_different_length_as_a_better_version():
    from backend.services.site_settings import download_profile_defaults

    youtube = source_site("https://www.youtube.com/@channel", "ytdlp")
    other = source_site("https://rumble.com/c/someone", "ytdlp")
    npo = source_site("https://npo.nl/start/serie/a-series", "npo")
    dailywire = source_site("https://www.dailywire.com/show/the-ben-shapiro-show", "dailywire")
    for site in (youtube, other, npo, dailywire):
        assert UpgradeImprovement.LENGTH in site.upgrade_checks.improvements

    # Only The Daily Wire counts it by default; YouTube starts at 3 minutes when it is turned on.
    assert "length" not in download_profile_defaults(youtube)["upgrade_improvements"]
    assert download_profile_defaults(youtube)["upgrade_length_minutes"] == 3
    assert "length" not in download_profile_defaults(other)["upgrade_improvements"]
    assert download_profile_defaults(other)["upgrade_length_minutes"] == 5
    assert download_profile_defaults(dailywire)["upgrade_improvements"] == ["length"]
    assert download_profile_defaults(dailywire)["upgrade_length_minutes"] == 5
    # Nothing NPO Start offers counts as better by default, so its check starts off.
    assert download_profile_defaults(npo)["upgrade_check"] is False
    assert download_profile_defaults(npo)["upgrade_improvements"] == []


def test_the_daily_wire_measures_the_stream_it_serves(monkeypatch):
    from sources.dailywire import status as dailywire

    playlists = {
        "https://cdn.test/master.m3u8": (
            "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=1280x720\n720/index.m3u8\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=854x480\n480/index.m3u8\n"
        ),
        "https://cdn.test/720/index.m3u8": "#EXTM3U\n#EXTINF:6.0,\na.ts\n#EXTINF:6.0,\nb.ts\n#EXTINF:2.5,\nc.ts\n#EXT-X-ENDLIST\n",
    }
    monkeypatch.setattr(dailywire, "_playlist", lambda url: (playlists[url], url))
    assert dailywire.stream_length("https://cdn.test/master.m3u8") == 14.5
    assert dailywire.stream_length("https://cdn.test/720/index.m3u8") == 14.5


@pytest.fixture
def session():
    from backend.db.core import Base
    import backend.db.models  # noqa: F401  (registers every table)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    if engine.dialect.name == "sqlite":
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


def test_add_media_offers_only_the_search_and_catalogue_of_added_sites():
    from backend.api.endpoints.sources.service import list_sources

    class OnlyYouTubeAdded:
        def scalars(self, _query):
            return ["youtube"]

    sources = {source.id: source for source in list_sources(OnlyYouTubeAdded())}
    assert {site.key: site.added for site in sources["ytdlp"].search_sites} == {
        "youtube": True, "twitch": False, "soundcloud": False, "dailymotion": False, "kick": False, "nebula": False,
        "lbry": False, "peertube": False, "niconico": False,
    }
    assert [(site.key, site.added) for site in sources["dailywire"].sites] == [("dailywire", False)]
    assert [(site.key, site.added) for site in sources["npo"].search_sites] == [("npo", False)]


def test_add_media_only_searches_twitch_once_its_api_is_set_up(monkeypatch, tmp_path):
    from backend.api.endpoints.sources.service import list_sources
    from sources import cookies, site_api_keys

    monkeypatch.setattr(cookies, "cookies_directory", lambda: tmp_path / "cookies")

    class TwitchAdded:
        def scalars(self, _query):
            return ["twitch"]

    def twitch():
        sources = {source.id: source for source in list_sources(TwitchAdded())}
        return next(site for site in sources["ytdlp"].search_sites if site.key == "twitch")

    assert twitch().added and not twitch().ready
    site_api_keys.save("twitch", {"client_id": "an-id", "client_secret": "a-secret"})
    assert twitch().ready


def test_only_links_on_a_site_vodloft_knows_are_media_links(session):
    from backend.db.models import Site as SiteRecord
    from backend.security.access import Access
    from backend.services.sites import media_links

    links = [
        "https://www.youtube.com/@Faith-May2005",  # A Site with a contract of its own
        "https://www.dailywire.com/show/a-show",  # A Site a Source is made for
        "https://streamyard.com/pal/d/5072102071074816",  # Only yt-dlp's generic extractor, and not added
        "https://www.example.com/clip.mp4",  # Not added yet
        "mailto:someone@example.com",
    ]
    assert media_links(session, Access.full(), links) == links[:2]

    # A site the user added, or that VODLoft has media from, is in VODLoft's Sites.
    session.add(SiteRecord(key="generic:example.com", name="example.com", domains=["example.com"]))
    session.flush()
    assert media_links(session, Access.full(), links) == [*links[:2], "https://www.example.com/clip.mp4"]


@pytest.mark.parametrize(("list_type", "name"), [
    ("album", "album"), ("playlist", "playlist"),
    # A set VODLoft hasn't looked up is either.
    (None, "album or playlist"),
])
def test_a_soundcloud_set_is_named_by_its_type_of_list(list_type, name):
    from backend.db.models import Collection
    from backend.services.sites import collection_names

    collection = Collection(
        sharing_url="https://soundcloud.com/flume/sets/palaces", source_key="ytdlp", kind="list", list_type=list_type,
    )

    assert collection_names(collection).singular == name


def test_a_new_collection_of_a_set_keeps_only_a_type_of_list_its_site_has():
    from backend.db.models import Collection
    from backend.services.collections import set_kind
    from backend.services.errors import ServiceError

    album = Collection(sharing_url="https://soundcloud.com/flume/sets/palaces", source_key="ytdlp", list_type="album")
    set_kind(album)
    assert album.list_type == "album"

    # A channel is no list.
    account = Collection(sharing_url="https://soundcloud.com/flume", source_key="ytdlp", type="music", list_type="album")
    set_kind(account)
    assert account.list_type is None

    with pytest.raises(ServiceError):
        set_kind(Collection(sharing_url="https://soundcloud.com/flume/sets/palaces", source_key="ytdlp", list_type="tracks"))


def test_a_site_of_its_own_domain_is_named_after_it_by_its_key():
    from sources import site_of

    site = site_of("generic:example.com")
    assert (site.name, site.initials, site.domains) == ("example.com", "EX", ("example.com",))
