"""NPO Start as a Source, against answers shaped like the ones npo.nl gives."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sources import Feature, LinkKind, PlaybackKind, get_source, sources_for
from sources.npo import NpoSource
from sources.npo.client import NpoNotFoundError
from sources.npo.source import parse_link

CLEAR = "https://vod.ak.md.npox.nl/legacy/package/clear/abc/index.m3u8?hdnts=x"
PROTECTED = "https://vod.ak.md.npox.nl/legacy/package/drmcbcs/abc/index.m3u8?hdnts=x"
SERIES = {
    "guid": "7c476bc8", "productId": "KN_1682194", "title": "Een huis vol", "slug": "een-huis-vol",
    "synopsis": "Een gezin met veel kinderen.", "type": "timeless_series",
    "images": [{"url": "https://images.npo.nl/portrait.jpg", "role": "portrait"}, {"url": "https://images.npo.nl/default.jpg", "role": "default"}],
    "broadcasters": ["NCRV"],
}


def _program(slug, number, season_key, season_guid, *, first_broadcast=1_400_000_000):
    return {
        "guid": f"guid-{slug}", "title": "Een huis vol", "slug": slug, "productId": f"NCRV_{slug}",
        "programKey": str(number), "synopsis": {"brief": None, "short": "Kort", "long": f"Aflevering {number}"},
        "durationInSeconds": 2100, "firstBroadcastDate": first_broadcast + number, "publishedDateTime": first_broadcast,
        "images": [{"url": f"https://images.npo.nl/{slug}.jpg", "role": "default"}],
        "season": {"guid": season_guid, "slug": f"seizoen-{season_key}", "seasonKey": str(season_key)},
        "series": {"guid": "7c476bc8", "slug": "een-huis-vol", "title": "Een huis vol", "type": "timeless_series"},
        "restrictions": [{"available": {"from": 0, "till": None}, "isStreamReady": True, "subscriptionType": "free"}],
    }


class FakeClient:
    def __init__(self):
        self.seasons = [
            {"guid": "s2", "seasonKey": "2", "slug": "seizoen-2", "label": None},
            {"guid": "s3", "seasonKey": "3", "slug": "seizoen-2_2", "label": None},
        ]
        # Newest first, as npo.nl lists them.
        self.programs = {
            "s2": [_program(f"een-huis-vol_{n}", n, 2, "s2") for n in (3, 2, 1)],
            "s3": [_program(f"een-huis-vol_{n}", n - 10, 3, "s3") for n in (12, 11)],
        }
        self.protected: set[str] = {"NCRV_een-huis-vol_12", "NCRV_een-huis-vol_11"}
        self.stream_requests: list[str] = []

    def series_detail(self, slug):
        if slug != "een-huis-vol":
            raise NpoNotFoundError("unknown")
        return SERIES

    def series_seasons(self, slug, series_type):
        assert series_type == "timeless_series"
        return self.seasons

    def programs_by_season(self, guid):
        return self.programs[guid]

    def program_detail(self, slug):
        for programs in self.programs.values():
            for program in programs:
                if program["slug"] == slug:
                    return program
        raise NpoNotFoundError("unknown")

    def stream_link(self, product_id, referrer_url):
        self.stream_requests.append(product_id)
        if product_id in self.protected:
            return {"stream": {"streamURL": PROTECTED, "streamProfile": "hls", "drm": {"licenseUrl": "https://license"}}}
        return {"stream": {"streamURL": CLEAR, "streamProfile": "hls", "drm": None}}

    def search(self, query, search_type):
        if search_type == "series":
            return [{"guid": "7c476bc8", "slug": "een-huis-vol", "title": "Een huis vol", "type": "timeless_series", "images": SERIES["images"]}]
        return [{**_program("de-film_1", 1, 1, "x"), "series": None, "title": "De film"}]


@pytest.fixture
def npo():
    client = FakeClient()
    return NpoSource(client), client


def test_npo_links_are_parsed_by_path():
    assert parse_link("https://npo.nl/start/serie/een-huis-vol/afleveringen") == (LinkKind.SHOW, "een-huis-vol")
    assert parse_link("https://npo.nl/start/serie/een-huis-vol/afleveringen/seizoen-2") == (LinkKind.SHOW, "een-huis-vol")
    assert parse_link("https://www.npo.nl/start/serie/een-huis-vol") == (LinkKind.SHOW, "een-huis-vol")
    assert parse_link("https://npo.nl/start/afspelen/een-huis-vol_62") == (LinkKind.VIDEO, "een-huis-vol_62")
    assert parse_link("https://npo.nl/start/serie/een-huis-vol/seizoen-2/een-huis-vol_62/afspelen") == (LinkKind.VIDEO, "een-huis-vol_62")
    assert parse_link("https://npo.nl/start") is None
    assert parse_link("https://npo.nl/nieuws/iets") is None


def test_npo_is_asked_before_yt_dlp_for_its_own_links():
    assert [source.id for source in sources_for("https://npo.nl/start/serie/een-huis-vol")][:2] == ["npo", "ytdlp"]
    assert get_source("npo").has(Feature.SEARCH)


def test_a_series_link_resolves_to_a_show(npo):
    source, _ = npo
    link = source.resolve("https://npo.nl/start/serie/een-huis-vol/afleveringen/seizoen-2")
    assert link.kind is LinkKind.SHOW
    assert link.url == "https://npo.nl/start/serie/een-huis-vol/afleveringen"
    assert link.image_url == "https://images.npo.nl/default.jpg"
    assert link.author_name == "NCRV"
    assert source.resolve("https://npo.nl/start/serie/bestaat-niet") is None


def test_an_episode_link_names_its_show_and_its_drm(npo):
    source, _ = npo
    clear = source.resolve("https://npo.nl/start/afspelen/een-huis-vol_2")
    assert clear.kind is LinkKind.EPISODE
    assert clear.show_url == "https://npo.nl/start/serie/een-huis-vol/afleveringen"
    assert clear.drm_protected is False
    assert source.resolve("https://npo.nl/start/afspelen/een-huis-vol_11").drm_protected is True


def test_episodes_keep_npo_seasons_and_numbers(npo):
    source, client = npo
    episodes = list(source.list_episodes("https://npo.nl/start/serie/een-huis-vol/afleveringen", known=frozenset({"een-huis-vol_1"})))
    assert [(e.slug, e.season.number, e.season.slug, e.episode_number, e.drm_protected) for e in episodes] == [
        ("een-huis-vol_3", 2, "seizoen-2", 3, False),
        ("een-huis-vol_2", 2, "seizoen-2", 2, False),
        ("een-huis-vol_12", 3, "seizoen-2_2", 2, True),
        ("een-huis-vol_11", 3, "seizoen-2_2", 1, True),
    ]
    first = episodes[0]
    assert first.url == "https://npo.nl/start/afspelen/een-huis-vol_3"
    assert first.description == "Aflevering 3"
    assert first.duration == 2100.0
    assert first.published_at == datetime.fromtimestamp(1_400_000_003, tz=timezone.utc)
    # A season whose first and last episode agree is not looked up episode by episode.
    assert len(client.stream_requests) == 4


def test_a_season_with_both_kinds_is_looked_up_per_episode(npo):
    source, client = npo
    client.protected = {"NCRV_een-huis-vol_3"}
    episodes = list(source.list_episodes("https://npo.nl/start/serie/een-huis-vol", known=frozenset()))
    assert {e.slug: e.drm_protected for e in episodes if e.season.number == 2} == {
        "een-huis-vol_3": True, "een-huis-vol_2": False, "een-huis-vol_1": False,
    }


def test_a_clear_stream_downloads_with_yt_dlp_and_a_protected_one_is_marked(npo):
    source, _ = npo
    playback = source.video_playback(slug="een-huis-vol_2", url="https://npo.nl/start/afspelen/een-huis-vol_2")
    assert playback.kind is PlaybackKind.YTDLP
    assert playback.url == CLEAR
    assert playback.drm_protected is False

    protected = source.video_playback(slug="x", url="https://npo.nl/start/afspelen/een-huis-vol_11")
    assert protected.drm_protected is True


def test_search_finds_series_and_programmes(npo):
    source, _ = npo
    results = source.search("huis").results
    assert [(r.kind, r.title, r.url) for r in results] == [
        (LinkKind.SHOW, "Een huis vol", "https://npo.nl/start/serie/een-huis-vol/afleveringen"),
        (LinkKind.VIDEO, "De film", "https://npo.nl/start/afspelen/de-film_1"),
    ]
    assert source.search("  ").results == []


@pytest.fixture
def session():
    from backend.db.core import Base
    import backend.db.models  # noqa: F401  (registers every table)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


def test_an_npo_series_is_indexed_with_its_own_seasons(npo, session):
    from backend.db.models import Episode, Show
    from task_manager.tasks.helpers.listed_shows import index_listed_show

    source, client = npo
    show = Show(
        uuid="uuid-huis", slug="een-huis-vol", source_key="npo", title="Een huis vol",
        sharing_url="https://npo.nl/start/serie/een-huis-vol/afleveringen", membership_level="FREE",
        type="podcast", episode_identifier="seasonal", author_name="NCRV", author_slug="ncrv",
    )
    session.add(show)
    session.commit()

    assert index_listed_show(session, show_id=show.id, source=source) == 5
    episodes = session.query(Episode).order_by(Episode.index).all()
    assert [(e.slug, e.episode_identifier, e.season.name, e.drm_protected) for e in episodes] == [
        ("een-huis-vol_1", "ep.S02E01", "Season 2", False),
        ("een-huis-vol_2", "ep.S02E02", "Season 2", False),
        ("een-huis-vol_3", "ep.S02E03", "Season 2", False),
        ("een-huis-vol_11", "ep.S03E01", "Season 3", True),
        ("een-huis-vol_12", "ep.S03E02", "Season 3", True),
    ]
    session.refresh(show)
    assert [(s.season_number, s.slug, s.index) for s in sorted(show.seasons, key=lambda s: s.index)] == [
        (2, "seizoen-2", 1), (3, "seizoen-2_2", 2),
    ]

    # A new episode keeps the number NPO gives it.
    client.programs["s2"].insert(0, _program("een-huis-vol_4", 4, 2, "s2"))
    session.commit()
    assert index_listed_show(session, show_id=show.id, source=source) == 1
    assert session.query(Episode).filter_by(slug="een-huis-vol_4").one().episode_identifier == "ep.S02E04"


def test_a_series_names_its_seasons_before_it_is_indexed(npo):
    source, _ = npo
    details = source.show_details("https://npo.nl/start/serie/een-huis-vol/afleveringen")
    assert [(season.slug, season.number, season.name) for season in details.seasons] == [
        ("seizoen-2", 2, "Season 2"), ("seizoen-2_2", 3, "Season 3"),
    ]


def test_seasons_picked_when_the_show_was_added_get_its_episodes(npo, session):
    from backend.db.models import Episode, Season, Show
    from task_manager.tasks.helpers.listed_shows import index_listed_show

    source, _ = npo
    show = Show(
        uuid="uuid-huis", slug="een-huis-vol", source_key="npo", title="Een huis vol",
        sharing_url="https://npo.nl/start/serie/een-huis-vol/afleveringen", membership_level="FREE",
        type="series", episode_identifier="seasonal", author_name="NCRV", author_slug="ncrv",
    )
    # As the Add Show wizard stores them: numbered in order, not by NPO.
    show.seasons = [
        Season(index=1, slug="seizoen-2", name="Season 2", season_number=1),
        Season(index=2, slug="seizoen-2_2", name="Season 3", season_number=2),
    ]
    session.add(show)
    session.commit()

    assert index_listed_show(session, show_id=show.id, source=source) == 5
    session.refresh(show)
    assert sorted((s.slug, s.season_number, s.index, len(s.episodes)) for s in show.seasons) == [
        ("seizoen-2", 2, 1, 3), ("seizoen-2_2", 3, 2, 2),
    ]
    assert session.query(Episode).filter_by(slug="een-huis-vol_11").one().episode_identifier == "ep.S03E01"


def _premium(program, *, free_until=None):
    """The programme as NPO lists one that needs NPO Plus, possibly after a free window."""
    restrictions = [{"available": {"from": 0, "till": None}, "isStreamReady": True, "subscriptionType": "premium"}]
    if free_until is not None:
        restrictions.append({"available": {"from": 0, "till": free_until}, "isStreamReady": True, "subscriptionType": "free"})
    return {**program, "restrictions": restrictions}


def test_needs_subscription_follows_the_restriction_open_right_now():
    from sources.npo.source import needs_subscription

    program = _program("een-huis-vol_1", 1, 2, "s2")
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    assert needs_subscription(program, now) is False
    assert needs_subscription(_premium(program), now) is True
    # Free for a while after it was broadcast, then only with NPO Plus. NPO sometimes counts in milliseconds.
    assert needs_subscription(_premium(program, free_until=int(now.timestamp()) + 60), now) is False
    assert needs_subscription(_premium(program, free_until=(int(now.timestamp()) + 60) * 1000), now) is False
    assert needs_subscription(_premium(program, free_until=int(now.timestamp()) - 60), now) is True
    assert needs_subscription({**program, "restrictions": []}, now) is False


def test_programmes_that_need_npo_plus_are_listed_and_not_looked_up(npo):
    source, client = npo
    client.programs["s2"] = [_premium(program) for program in client.programs["s2"]]
    episodes = list(source.list_episodes("https://npo.nl/start/serie/een-huis-vol", known=frozenset()))
    assert {e.slug: (e.needs_subscription, e.drm_protected) for e in episodes} == {
        "een-huis-vol_3": (True, False), "een-huis-vol_2": (True, False), "een-huis-vol_1": (True, False),
        "een-huis-vol_12": (False, True), "een-huis-vol_11": (False, True),
    }
    # Only the free season's two ends asked for a stream.
    assert client.stream_requests == ["NCRV_een-huis-vol_12", "NCRV_een-huis-vol_11"]
    assert source.subscription_name == "NPO Plus"


def test_a_programme_that_needs_npo_plus_resolves_and_plays_as_such(npo):
    source, client = npo
    client.programs["s2"] = [_premium(program) for program in client.programs["s2"]]
    link = source.resolve("https://npo.nl/start/afspelen/een-huis-vol_2")
    assert (link.needs_subscription, link.drm_protected) == (True, False)
    assert source.video_details("https://npo.nl/start/afspelen/een-huis-vol_2").needs_subscription is True
    playback = source.video_playback(slug="een-huis-vol_2", url="https://npo.nl/start/afspelen/een-huis-vol_2")
    assert playback.needs_subscription is True
    assert client.stream_requests == []


def test_episodes_that_need_npo_plus_are_stored_but_not_planned(npo, session):
    from backend.db.models import DownloadProfile, Episode, Show, ShowLocalMediaProfile
    from task_manager.tasks.helpers.listed_shows import index_listed_show
    from task_manager.tasks.workers.download_profile_worker._helpers import get_download_profile_episodes

    source, client = npo
    client.programs["s2"] = [_premium(program) for program in client.programs["s2"]]
    client.protected = set()
    show = Show(
        uuid="uuid-huis", slug="een-huis-vol", source_key="npo", title="Een huis vol",
        sharing_url="https://npo.nl/start/serie/een-huis-vol/afleveringen", membership_level="FREE",
        type="series", episode_identifier="seasonal", author_name="NCRV", author_slug="ncrv",
    )
    session.add(show)
    session.commit()
    index_listed_show(session, show_id=show.id, source=source)
    assert {e.slug: e.needs_subscription for e in session.query(Episode)} == {
        "een-huis-vol_1": True, "een-huis-vol_2": True, "een-huis-vol_3": True,
        "een-huis-vol_11": False, "een-huis-vol_12": False,
    }
    local = ShowLocalMediaProfile(slug="shows", name="Shows", preferred_format="format_1080p",
                                  output_template="/downloads/{{ show_title }}/{{ episode_title }}.ext")
    profile = DownloadProfile(
        show=show, local_media_profile=local, enable_profile=True, ep_id_type_list=["ep"],
        download_with_countdown=False, redownload_final=False, download_days_in_past=0,
        download_episode_count=0, delete_older_episodes=False,
    )
    session.add_all([local, profile])
    session.flush()
    profile.seasons = list(show.seasons)
    assert sorted(e.slug for e in get_download_profile_episodes(session, profile)) == ["een-huis-vol_11", "een-huis-vol_12"]


def test_the_background_migration_marks_stored_programmes_that_need_npo_plus(npo, session, monkeypatch):
    import asyncio
    import importlib

    from backend.db.models import Episode, Show, Video
    from task_manager.tasks.helpers.listed_shows import index_listed_show

    migration = importlib.import_module("backend.db.background_migrations.versions.5e2b8c71d0a4_npo_plus_labels")
    source, client = npo
    show = Show(
        uuid="uuid-huis", slug="een-huis-vol", source_key="npo", title="Een huis vol",
        sharing_url="https://npo.nl/start/serie/een-huis-vol/afleveringen", membership_level="FREE",
        type="series", episode_identifier="seasonal", author_name="NCRV", author_slug="ncrv",
    )
    session.add(show)
    session.add(Video(
        uuid="uuid-video", type="video", source_key="npo", slug="een-huis-vol_2", title="Een huis vol",
        sharing_url="https://npo.nl/start/afspelen/een-huis-vol_2", duration=0.0,
    ))
    session.commit()
    # Indexed by an older VODLoft, before NPO started asking for NPO Plus.
    index_listed_show(session, show_id=show.id, source=source)
    client.programs["s2"] = [_premium(program) for program in client.programs["s2"]]

    bind = session.get_bind()
    monkeypatch.setattr(migration, "get_session", lambda: sessionmaker(bind=bind)())
    monkeypatch.setattr(migration, "NpoClient", lambda: client)

    class Context:
        def raise_if_cancelled(self):
            pass

        def update_progress(self, *args):
            pass

    session.commit()
    asyncio.run(migration.migrate(Context()))
    session.expire_all()
    assert {e.slug for e in session.query(Episode).filter_by(needs_subscription=True)} == {
        "een-huis-vol_1", "een-huis-vol_2", "een-huis-vol_3",
    }
    assert session.query(Video).one().needs_subscription is True


COOKIES = "# Netscape HTTP Cookie File\n.npo.nl\tTRUE\t/\tTRUE\t0\tsession\tabc\n"


@pytest.fixture
def signed_in(tmp_path, monkeypatch):
    from sources.npo import account

    monkeypatch.setattr(account, "cookies_path", lambda: tmp_path / "npo" / "cookies.txt")
    return account


def test_a_cookies_file_signs_npo_start_in(npo, signed_in):
    source, _ = npo
    assert source.has(Feature.COOKIES) and source.cookies_help
    assert source.subscription_active is False
    with pytest.raises(ValueError, match="no npo.nl cookies"):
        source.save_cookies(b"# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tTRUE\t0\tsession\tabc\n")
    with pytest.raises(ValueError, match="Netscape"):
        source.save_cookies(b"not a cookies file")
    source.save_cookies(COOKIES.encode())
    assert source.has_cookies() and source.subscription_active is True
    assert [cookie.name for cookie in signed_in.load_cookies()] == ["session"]
    source.remove_cookies()
    assert source.subscription_active is False


def test_signed_in_programmes_that_need_npo_plus_are_checked_and_played(npo, signed_in):
    source, client = npo
    source.save_cookies(COOKIES.encode())
    client.programs["s2"] = [_premium(program) for program in client.programs["s2"]]
    client.protected = {"NCRV_een-huis-vol_1"}
    episodes = list(source.list_episodes("https://npo.nl/start/serie/een-huis-vol", known=frozenset()))
    assert {e.slug: (e.needs_subscription, e.drm_protected) for e in episodes if e.season.number == 2} == {
        "een-huis-vol_3": (True, False), "een-huis-vol_2": (True, False), "een-huis-vol_1": (True, True),
    }
    playback = source.video_playback(slug="een-huis-vol_2", url="https://npo.nl/start/afspelen/een-huis-vol_2")
    assert (playback.needs_subscription, playback.url) == (False, CLEAR)


def test_a_sign_in_without_npo_plus_still_cannot_play_them(npo, signed_in):
    from sources.npo.client import NpoError

    source, client = npo
    source.save_cookies(COOKIES.encode())
    client.programs["s2"] = [_premium(program) for program in client.programs["s2"]]

    def refused(product_id, referrer_url):
        raise NpoError("NPO Start answered with HTTP 403")
    client.stream_link = refused
    playback = source.video_playback(slug="een-huis-vol_2", url="https://npo.nl/start/afspelen/een-huis-vol_2")
    assert playback.needs_subscription is True


def test_signed_in_episodes_that_need_npo_plus_are_planned(npo, session, signed_in):
    from backend.db.models import DownloadProfile, Show, ShowLocalMediaProfile
    from task_manager.tasks.helpers.listed_shows import index_listed_show
    from task_manager.tasks.workers.download_profile_worker._helpers import get_download_profile_episodes

    source, client = npo
    client.programs["s2"] = [_premium(program) for program in client.programs["s2"]]
    client.protected = set()
    show = Show(
        uuid="uuid-huis", slug="een-huis-vol", source_key="npo", title="Een huis vol",
        sharing_url="https://npo.nl/start/serie/een-huis-vol/afleveringen", membership_level="FREE",
        type="series", episode_identifier="seasonal", author_name="NCRV", author_slug="ncrv",
    )
    session.add(show)
    session.commit()
    index_listed_show(session, show_id=show.id, source=source)
    local = ShowLocalMediaProfile(slug="shows", name="Shows", preferred_format="format_1080p",
                                  output_template="/downloads/{{ show_title }}/{{ episode_title }}.ext")
    profile = DownloadProfile(
        show=show, local_media_profile=local, enable_profile=True, ep_id_type_list=["ep"],
        download_with_countdown=False, redownload_final=False, download_days_in_past=0,
        download_episode_count=0, delete_older_episodes=False,
    )
    session.add_all([local, profile])
    session.flush()
    profile.seasons = list(show.seasons)
    assert len(get_download_profile_episodes(session, profile)) == 2
    source.save_cookies(COOKIES.encode())
    assert len(get_download_profile_episodes(session, profile)) == 5


def test_signed_in_npo_downloads_run_one_at_a_time(npo, signed_in):
    from downloader.capacity import DownloadResources

    source, _ = npo
    assert source.download_streams is None
    source.save_cookies(COOKIES.encode())
    assert source.download_streams == 1
    resources = DownloadResources()
    lane = resources.lane("source:npo", 1)
    assert resources.lane("source:npo", 1) is lane
    with lane.acquire(should_cancel=lambda: False, waiting=lambda _: None):
        with pytest.raises(Exception, match="Canceled"):
            with lane.acquire(should_cancel=lambda: True, waiting=lambda _: None):
                pass
