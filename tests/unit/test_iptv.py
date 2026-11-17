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
    assert iptv.media_name(db_session, profile, playing.episode) == "video.m3u8"


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
    from backend.services.iptv import media_name, playing_now

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=NOW - timedelta(minutes=10))
    profile = _channel(db_session, collection, preferred_format="format_audio_only", live=False)

    assert media_name(db_session, profile, playing_now(db_session, profile, NOW).episode) == "audio.m4a"


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


def test_the_playlist_lists_each_channel_with_its_number_group_logo_and_addresses(db_session):
    from backend.api.endpoints.iptv.service import render_playlist

    profile = _channel(db_session, _collection(db_session), number=12, overwrite_collection_title='The "Show"')

    playlist = render_playlist([profile], base_url="https://vodloft.test", guide_url="https://vodloft.test/iptv/t/guide.xml")

    assert playlist.splitlines() == [
        '#EXTM3U url-tvg="https://vodloft.test/iptv/t/guide.xml" x-tvg-url="https://vodloft.test/iptv/t/guide.xml"',
        f'#EXTINF:-1 tvg-id="vodloft-{profile.id}" tvg-name="The \'Show\'" tvg-logo="https://images.test/show.jpg" '
        'tvg-chno="12" group-title="The Daily Wire" catchup="default" catchup-days="7" '
        'catchup-source="https://vodloft.test/iptv/show-token/catchup.m3u8?utc={utc}&lutc={lutc}",The "Show"',
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


def test_an_off_air_channel_fills_the_gaps_with_off_air_and_plays_the_off_air_screen(db_session):
    from backend.api.endpoints.iptv.service import render_guide
    from backend.services.iptv import channel_programmes, playing_now

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=NOW - timedelta(hours=3), minutes=30)
    _episode(db_session, collection, 2, at=NOW - timedelta(minutes=10), minutes=30)
    profile = _channel(db_session, collection, between_live_episodes="off_air", catch_up_days=1)

    slots = [
        (programme.episode.index if programme.episode else None, programme.start, programme.stop)
        for programme in channel_programmes(db_session, profile, NOW)
    ]

    assert slots == [
        (None, NOW - timedelta(days=1), NOW - timedelta(hours=3)),
        (1, NOW - timedelta(hours=3), NOW - timedelta(hours=2, minutes=30)),
        (None, NOW - timedelta(hours=2, minutes=30), NOW - timedelta(minutes=10)),
        (2, NOW - timedelta(minutes=10), NOW + timedelta(minutes=20)),
        (None, NOW + timedelta(minutes=20), NOW + timedelta(days=1)),
    ]
    assert playing_now(db_session, profile, NOW).episode.index == 2
    assert playing_now(db_session, profile, NOW + timedelta(hours=1)).episode is None
    titles = [element.findtext("title") for element in ET.fromstring(render_guide(db_session, [profile], NOW)).iter("programme")]
    assert titles == ["Off air", "Episode 1", "Off air", "Episode 2", "Off air"]


def test_a_channel_only_on_while_live_is_listed_only_then(db_session):
    from backend.services.iptv import channel_programmes, listed_channels, playing_now

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=NOW - timedelta(minutes=10), minutes=30)
    profile = _channel(db_session, collection, between_live_episodes="hide_channel")

    assert [programme.repeat for programme in channel_programmes(db_session, profile, NOW)] == [False]
    assert playing_now(db_session, profile, NOW) is None
    assert listed_channels(db_session, [profile], NOW) == []

    _episode(db_session, collection, 2, at=NOW - timedelta(minutes=5), minutes=0, status="live")

    assert playing_now(db_session, profile, NOW).live
    assert listed_channels(db_session, [profile], NOW) == [profile]


def test_catch_up_plays_the_episode_of_a_guide_slot_within_the_window(db_session):
    from backend.services.iptv import catch_up_programme, channel_programmes

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=NOW - timedelta(days=3), minutes=30)
    _episode(db_session, collection, 2, at=NOW - timedelta(hours=2), minutes=30)
    profile = _channel(db_session, collection, catch_up_days=2)

    assert channel_programmes(db_session, profile, NOW)[0].stop > NOW - timedelta(days=2)
    assert catch_up_programme(db_session, profile, NOW - timedelta(hours=2), NOW).episode.index == 2
    # A slot of the loop of an episode plays that episode, also when the app asks a little early.
    assert catch_up_programme(db_session, profile, NOW - timedelta(days=1, seconds=30), NOW).episode.index == 1
    assert catch_up_programme(db_session, profile, NOW - timedelta(days=3), NOW) is None
    assert catch_up_programme(db_session, profile, NOW + timedelta(hours=1), NOW) is None


def test_catch_up_has_nothing_to_play_while_the_channel_was_off_air(db_session):
    from backend.services.iptv import catch_up_programme

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=NOW - timedelta(hours=3), minutes=30)
    profile = _channel(db_session, collection, between_live_episodes="off_air")

    assert catch_up_programme(db_session, profile, NOW - timedelta(hours=3), NOW).episode.index == 1
    assert catch_up_programme(db_session, profile, NOW - timedelta(hours=1), NOW) is None


def test_the_off_air_screen_plays_on_a_loop_until_the_channel_has_something_on(db_session):
    from backend.api.endpoints.iptv.service import render_off_air

    on_air = render_off_air(NOW, segment_url="https://vodloft.test/iptv/off-air.ts", ended=False).splitlines()
    ended = render_off_air(NOW, segment_url="https://vodloft.test/iptv/off-air.ts", ended=True).splitlines()

    sequence = int(NOW.timestamp()) // 6
    assert f"#EXT-X-MEDIA-SEQUENCE:{sequence}" in on_air
    assert on_air.count("https://vodloft.test/iptv/off-air.ts") == 3
    assert "#EXT-X-ENDLIST" not in on_air
    assert ended[-1] == "#EXT-X-ENDLIST"


def test_the_episode_playlist_lists_every_episode_of_the_channel_on_its_own(db_session):
    from backend.api.endpoints.iptv.service import render_episode_playlist

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=NOW - timedelta(days=2), minutes=30)
    _episode(db_session, collection, 2, at=NOW - timedelta(days=1), minutes=0)
    profile = _channel(db_session, collection, list_episodes=True)

    playlist = render_episode_playlist(db_session, [profile], base_url="https://vodloft.test")

    assert playlist.splitlines() == [
        "#EXTM3U",
        '#EXTINF:-1 group-title="The Show",Episode 2',
        "https://vodloft.test/feeds/iptv/show-token/episodes/show-2/video.m3u8",
        '#EXTINF:1800 group-title="The Show",Episode 1',
        "https://vodloft.test/feeds/iptv/show-token/episodes/show-1/video.m3u8",
    ]


def test_a_channel_only_on_while_live_needs_live_episodes():
    from pydantic import ValidationError

    from backend.api.models.iptv_stream_profile import IptvStreamProfileAPIUpdate

    with pytest.raises(ValidationError, match="never listed"):
        IptvStreamProfileAPIUpdate(
            title="Show", enable_profile=True, use_downloads=False, use_source_stream=True,
            preferred_format="format_1080p", prefer_exact_match=False, stream_live_episodes=False,
            between_live_episodes="hide_channel",
        )
