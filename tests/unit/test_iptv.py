"""IPTV stream profiles: the channels a playlist lists, their programme guide and what they play now."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

NOW = datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_session():
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    session = Session(engine)
    Base.metadata.create_all(engine)
    yield session
    session.close()
    engine.dispose()


def _collection(session, slug="show"):
    from backend.db.models import Collection, Season

    collection = Collection(
        source_key="dailywire", uuid=f"{slug}-uuid", slug=slug, title=f"The {slug.title()}", description="About",
        sharing_url=f"https://www.dailywire.com/{slug}", membership_level="FREE", type="podcast",
        episode_identifier="numbered", author_name="Host", author_slug="host",
        thumbnail_square_path=f"https://images.test/{slug}.jpg",
    )
    session.add(collection)
    session.add(Season(collection=collection, index=1, slug=f"{slug}-season", name="Season 1", season_number=1))
    session.flush()
    return collection


def _episode(session, collection, number, *, at, minutes=30.0, status="published_final"):
    from backend.db.models import Episode

    episode = Episode(
        source_key="dailywire", uuid=f"{collection.slug}-{number}", type="episode", collection=collection,
        season=collection.seasons[0], index=number, episode_identifier=f"ep.{number}",
        slug=f"{collection.slug}-{number}", title=f"Episode {number}", description="What happens",
        duration=minutes * 60 if minutes else None, publish_status=status,
        sharing_url=f"https://www.dailywire.com/{collection.slug}-{number}",
        published_date=at if status == "published_final" else None,
        went_live_date=at if status == "live" else None,
        scheduled_date=at if status == "scheduled" else None,
    )
    session.add(episode)
    session.flush()
    return episode


def _channel(session, collection, *, number=1, token=None, owner=None, live=True, preferred_format="format_1080p", **values):
    from backend.db.models import IptvStreamProfile

    profile = IptvStreamProfile(
        collection=collection, enable_profile=True, token=token or f"{collection.slug}-token",
        use_downloads=False, use_source_stream=True, preferred_format=preferred_format, prefer_exact_match=False,
        ep_id_type_list=["ep"], stream_live_episodes=live, channel_number=number, owner_user_id=owner, **values,
    )
    session.add(profile)
    session.flush()
    return profile


def _slots(programmes):
    return [
        (programme.episode.index, programme.start.strftime("%H:%M"), programme.stop.strftime("%H:%M"), programme.repeat)
        for programme in programmes
    ]


def test_an_episode_fills_its_slot_and_the_channel_loops_it_until_the_next_one(db_session):
    from backend.services.iptv import channel_programmes

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=NOW - timedelta(hours=2), minutes=40)
    _episode(db_session, collection, 2, at=NOW - timedelta(minutes=30), minutes=7)
    profile = _channel(db_session, collection)

    programmes = channel_programmes(db_session, profile, NOW)

    assert _slots(programmes)[:5] == [
        (1, "18:00", "18:40", False),
        (1, "18:40", "19:20", True),
        (1, "19:20", "19:30", True),
        # Seven minutes take two slots of five, and its loop shows as blocks of three plays.
        (2, "19:30", "19:40", False),
        (2, "19:40", "20:10", True),
    ]
    assert programmes[-1].stop == NOW + timedelta(days=1)


def test_an_episode_ends_where_the_next_one_starts(db_session):
    from backend.services.iptv import channel_programmes

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=NOW - timedelta(hours=1), minutes=60)
    _episode(db_session, collection, 2, at=NOW - timedelta(minutes=40), minutes=10)

    assert _slots(channel_programmes(db_session, _channel(db_session, collection), NOW))[:2] == [
        (1, "19:00", "19:20", False),
        (2, "19:20", "19:30", False),
    ]


def test_the_guide_reaches_a_week_back(db_session):
    from backend.services.iptv import channel_programmes

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=NOW - timedelta(days=30), minutes=60)

    programmes = channel_programmes(db_session, _channel(db_session, collection), NOW)

    assert programmes[0].start <= NOW - timedelta(days=7) < programmes[0].stop
    assert all(programme.repeat for programme in programmes)


def test_a_live_episode_runs_past_now_and_the_channel_plays_it_live(db_session):
    from backend.services import iptv

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=NOW - timedelta(hours=3), minutes=30)
    _episode(db_session, collection, 2, at=NOW - timedelta(minutes=12), minutes=0, status="live")
    profile = _channel(db_session, collection)

    playing = iptv.playing_now(db_session, profile, NOW)

    assert (playing.episode.index, playing.live) == (2, True)
    assert playing.stop >= NOW + timedelta(minutes=30)
    assert iptv.channel_media_name(db_session, profile, playing) == "video.m3u8"


def test_a_scheduled_episode_is_upcoming_and_the_loop_stops_for_it(db_session):
    from backend.services.iptv import channel_programmes, playing_now

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=NOW - timedelta(hours=1), minutes=30)
    _episode(db_session, collection, 2, at=NOW + timedelta(hours=1), minutes=60, status="scheduled")
    profile = _channel(db_session, collection)

    programmes = channel_programmes(db_session, profile, NOW)

    assert (programmes[-1].episode.index, programmes[-1].upcoming) == (2, True)
    assert programmes[-2].stop == NOW + timedelta(hours=1)
    assert playing_now(db_session, profile, NOW).episode.index == 1


def test_an_audio_channel_plays_the_episode_audio(db_session):
    from backend.services.iptv import channel_media_name, playing_now

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=NOW - timedelta(minutes=10))
    profile = _channel(db_session, collection, preferred_format="format_audio_only", live=False)

    assert channel_media_name(db_session, profile, playing_now(db_session, profile, NOW)) == "audio.m4a"


def test_a_channel_token_opens_that_channel_and_a_user_token_all_of_theirs(db_session):
    from backend.db.models.user import User
    from backend.services.errors import NotFoundError
    from backend.services.iptv import channels_for_token

    owner = User(username="owner", password_hash="x", stream_token="owner-token")
    other = User(username="other", password_hash="x", stream_token="other-token")
    db_session.add_all([owner, other])
    db_session.flush()
    news = _channel(db_session, _collection(db_session, "news"), number=7, owner=owner.id)
    talk = _channel(db_session, _collection(db_session, "talk"), number=3, owner=owner.id)
    _channel(db_session, _collection(db_session, "else"), number=1, owner=other.id)

    assert channels_for_token(db_session, "news-token") == [news]
    assert channels_for_token(db_session, "owner-token") == [talk, news]

    owner.is_enabled = False
    with pytest.raises(NotFoundError):
        channels_for_token(db_session, "owner-token")
    with pytest.raises(NotFoundError):
        channels_for_token(db_session, "news-token")
    with pytest.raises(NotFoundError):
        channels_for_token(db_session, "unknown")


def test_the_install_token_opens_every_channel_only_without_user_accounts(db_session):
    from backend.db.models import Settings
    from backend.services.errors import NotFoundError
    from backend.services.iptv import channels_for_token

    settings = Settings(stream_token="install-token")
    db_session.add(settings)
    one = _channel(db_session, _collection(db_session, "one"), number=1)
    two = _channel(db_session, _collection(db_session, "two"), number=2)

    assert channels_for_token(db_session, "install-token") == [one, two]
    settings.user_accounts_enabled = True
    with pytest.raises(NotFoundError):
        channels_for_token(db_session, "install-token")


def test_the_playlist_lists_each_channel_with_its_number_group_logo_and_address(db_session):
    from backend.api.endpoints.iptv.service import render_playlist

    profile = _channel(db_session, _collection(db_session), number=12, overwrite_collection_title='The "Show"')

    playlist = render_playlist([profile], base_url="https://vodloft.test", guide_url="https://vodloft.test/iptv/t/guide.xml")

    assert playlist.splitlines() == [
        '#EXTM3U url-tvg="https://vodloft.test/iptv/t/guide.xml" x-tvg-url="https://vodloft.test/iptv/t/guide.xml"',
        f'#EXTINF:-1 tvg-id="vodloft-{profile.id}" tvg-name="The \'Show\'" tvg-logo="https://images.test/show.jpg" '
        'tvg-chno="12" group-title="The Daily Wire",The "Show"',
        "https://vodloft.test/iptv/show-token/channel.m3u8",
    ]


def test_the_guide_is_xmltv_with_the_channels_and_their_programmes(db_session):
    from backend.api.endpoints.iptv.service import render_guide

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=NOW - timedelta(minutes=50), minutes=30)
    profile = _channel(db_session, collection, number=4, channel_group="News")

    tv = ET.fromstring(render_guide(db_session, [profile], NOW))

    channel = tv.find("channel")
    assert channel.get("id") == f"vodloft-{profile.id}"
    assert [name.text for name in channel.findall("display-name")] == ["The Show", "4"]
    first, repeat = tv.findall("programme")[:2]
    assert (first.get("start"), first.get("stop")) == ("20261116191000 +0000", "20261116194000 +0000")
    assert (first.findtext("title"), first.findtext("desc"), first.find("previously-shown")) == (
        "Episode 1", "What happens", None,
    )
    assert repeat.find("previously-shown") is not None


def test_a_new_channel_takes_the_next_free_number_of_its_owner(db_session):
    from backend.api.endpoints.iptv_stream_profiles.service import create_stream_profile_iptv
    from backend.api.models.iptv_stream_profile import IptvStreamProfileAPICreate
    from backend.security.access import Access

    _channel(db_session, _collection(db_session, "first"), number=5)
    collection = _collection(db_session, "second")
    body = IptvStreamProfileAPICreate(
        collection_id=collection.id, title=collection.title, enable_profile=True, use_downloads=False,
        use_source_stream=True, preferred_format="format_1080p", prefer_exact_match=False, channel_group="  ",
    )

    created = create_stream_profile_iptv(db_session, body, Access.full())

    assert (created.channel_number, created.channel_group) == (6, None)
    assert created.playlist_path.startswith("/iptv/") and created.playlist_path.endswith("/playlist.m3u")
