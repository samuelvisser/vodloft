"""A collection indexed from several links: where each link's videos go, and which link keeps a shared video."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from sources import ItemRef, ItemRefresh, VideoDetails
from test_ytdlp_collections import ListedSource, _video, listed as _listed, session  # noqa: F401

CHANNEL = "https://www.youtube.com/@a-channel/videos"
SERIES = "https://www.youtube.com/playlist?list=PLseries"
BONUS = "https://www.youtube.com/playlist?list=PLbonus"


class LinksSource(ListedSource):
    """Lists each link's own videos, and on a refresh says which of them the link still lists."""

    def __init__(self):
        super().__init__()
        self.links: dict[str, list[VideoDetails]] = {}
        self.listed: dict[str, frozenset[str] | None] = {}

    def list_episodes(self, url, *, known):
        self.known_seen.append(known)
        return iter([video for video in self.links.get(url, []) if video.slug not in known])

    def latest_items(self, url):
        return [ItemRef(video.slug, video.url) for video in self.links.get(url, [])]

    def item_details(self, items):
        everything = {video.slug: video for videos in self.links.values() for video in videos}
        return {item.slug: everything.get(item.slug) for item in items}

    def refresh_items(self, url, items):
        return ItemRefresh(listed=self.listed.get(url))


@pytest.fixture
def links_source(monkeypatch):
    from sources import registry

    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    return registry.register(LinksSource())


def _collection(session, *links):
    """A collection of the channel, with the extra links (url, title, placement) above it in the order."""
    from backend.db.models import Collection, CollectionLink

    collection = Collection(
        uuid="uuid-channel", slug="a-channel", source_key="listed", title="A Channel", sharing_url=CHANNEL,
        membership_level="FREE", type="series", episode_identifier="seasonal", author_name="A Channel",
        author_slug="a-channel",
    )
    collection.links[0].position = len(links)
    for position, (url, title, placement) in enumerate(links):
        collection.links.append(CollectionLink(url=url, title=title, placement=placement, position=position))
    session.add(collection)
    session.commit()
    return collection


def _episodes(session):
    from backend.db.models import Episode

    session.expire_all()
    return {
        episode.slug: (episode.season.name, episode.episode_identifier)
        for episode in session.scalars(select(Episode).order_by(Episode.index))
    }


def _index(session, collection, source):
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    return index_listed_collection(session, collection_id=collection.id, source=source)


def test_a_new_collection_has_the_link_it_was_added_with(session):
    collection = _collection(session)

    assert [(link.url, link.position, link.placement) for link in collection.links] == [(CHANNEL, 0, "site_seasons")]


def test_a_playlist_becomes_a_named_season_and_the_channel_a_season_per_year(links_source, session):
    collection = _collection(session, (SERIES, "The Series", "one_season"))
    links_source.links = {
        SERIES: [_video("s1", 2023, 2), _video("s2", 2024, 6)],
        CHANNEL: [_video("s1", 2023, 2), _video("v1", 2023, 5), _video("s2", 2024, 6), _video("v2", 2024, 1)],
    }

    assert _index(session, collection, links_source) == 4

    assert _episodes(session) == {
        "s1": ("The Series", "ep.S01E01"),
        "s2": ("The Series", "ep.S01E02"),
        "v1": ("2023", "ep.S2023E01"),
        "v2": ("2024", "ep.S2024E01"),
    }
    # The channel looked up neither video of the playlist again, and remembers it lists them.
    assert links_source.known_seen == [frozenset(), frozenset()]
    assert _index(session, collection, links_source) == 0
    assert links_source.known_seen[2:] == [frozenset({"s1", "s2"}), frozenset({"s1", "v1", "s2", "v2"})]


def test_single_videos_can_be_specials(links_source, session):
    collection = _collection(session, (BONUS, "Bonus", "specials"))
    links_source.links = {BONUS: [_video("b1", 2022)], CHANNEL: [_video("v1", 2023)]}

    _index(session, collection, links_source)

    assert _episodes(session) == {"b1": ("Specials", "ep.S00E01"), "v1": ("2023", "ep.S2023E01")}


def test_a_video_a_higher_link_lists_later_moves_there_until_it_has_a_file(links_source, session):
    from backend.db.models import CollectionLocalMediaProfile, Episode, EpisodeMediaDownload

    collection = _collection(session, (SERIES, "The Series", "one_season"))
    links_source.links = {CHANNEL: [_video("v1", 2023), _video("v2", 2023, 3)]}
    _index(session, collection, links_source)
    downloaded = session.scalar(select(Episode).where(Episode.slug == "v2"))
    local = CollectionLocalMediaProfile(
        slug="collections", name="Collections", preferred_format="format_1080p",
        output_template="/downloads/{{ collection_title }}/{{ episode_title }}.ext",
    )
    session.add(local)
    session.flush()
    session.add(EpisodeMediaDownload(media_item_id=downloaded.id, local_media_profile_id=local.id, file_path="/library/v2.mp4"))
    session.commit()

    links_source.links[SERIES] = [_video("v1", 2023), _video("v2", 2023, 3)]
    _index(session, collection, links_source)

    assert _episodes(session) == {"v1": ("The Series", "ep.S01E01"), "v2": ("2023", "ep.S2023E02")}


def test_the_quick_check_looks_at_every_link(links_source, session):
    from task_manager.tasks.workers.fetch_new_episodes.quick_check import _check_collection

    collection = _collection(session, (SERIES, "The Series", "one_season"))
    links_source.links = {CHANNEL: [_video("v1", 2023)]}
    _index(session, collection, links_source)

    links_source.links = {SERIES: [_video("s1", 2024), _video("v1", 2023)], CHANNEL: [_video("s1", 2024), _video("v1", 2023)]}
    assert _check_collection(session, collection=session.get(type(collection), collection.id), source=links_source) == 1

    # The playlist claims the video the channel gave first, then adds its new one after it.
    assert _episodes(session) == {"v1": ("The Series", "ep.S01E01"), "s1": ("The Series", "ep.S01E02")}


def test_a_video_taken_out_of_a_playlist_goes_back_to_the_channel(links_source, session):
    from task_manager.tasks.helpers.listed_collections import refresh_listed_collection

    collection = _collection(session, (SERIES, "The Series", "one_season"))
    links_source.links = {SERIES: [_video("s1", 2023), _video("s2", 2023, 4)], CHANNEL: [_video("s1", 2023), _video("s2", 2023, 4)]}
    _index(session, collection, links_source)

    links_source.listed = {SERIES: frozenset({"s2"})}
    counts = refresh_listed_collection(session, collection_id=collection.id, source=links_source)

    assert counts.removed == 0
    assert _episodes(session) == {"s1": ("2023", "ep.S2023E01"), "s2": ("The Series", "ep.S01E02")}


def test_a_video_only_its_own_link_had_stays_when_it_leaves(links_source, session):
    from task_manager.tasks.helpers.listed_collections import refresh_listed_collection

    collection = _collection(session, (SERIES, "The Series", "one_season"))
    links_source.links = {SERIES: [_video("s1", 2023)]}
    _index(session, collection, links_source)

    links_source.listed = {SERIES: frozenset()}
    refresh_listed_collection(session, collection_id=collection.id, source=links_source)

    assert _episodes(session) == {"s1": ("The Series", "ep.S01E01")}


SHORTS = "https://www.youtube.com/@a-channel/shorts"


def _channel_collections(session):
    """A channel's main collection of its Videos, and a collection of its own for its Shorts, which the channel's
    order puts above Videos."""
    from backend.db.models import Channel, Collection, CollectionLink

    from backend.services.sites import site_record
    from sources import get_source

    youtube = get_source("ytdlp").site_for(CHANNEL)
    channel = Channel(
        uuid="uuid-ch", slug="a-channel", source_key="listed", site_key=site_record(session, youtube).key, site_ref="UCa",
        title="A Channel",
    )
    session.add(channel)
    made = []
    for slug, title, url, position in (("a-channel", "A Channel", CHANNEL, 5), ("a-channel-shorts", "A Channel Shorts", SHORTS, 3)):
        collection = Collection(
            uuid=f"uuid-{slug}", slug=slug, source_key="listed", title=title, sharing_url=url, membership_level="FREE",
            type="series", episode_identifier="seasonal", author_name="A Channel", author_slug="a-channel",
            links=[CollectionLink(url=url, position=position)],
        )
        collection.channel = channel
        session.add(collection)
        made.append(collection)
    session.commit()
    return made


def _held(session):
    from backend.db.models import Episode

    session.expire_all()
    return {episode.slug: (episode.collection.slug, episode.episode_identifier) for episode in session.scalars(select(Episode))}


def test_a_video_the_channel_keeps_in_another_collection_is_not_added_twice(links_source, session):
    main, shorts = _channel_collections(session)
    links_source.links = {SHORTS: [_video("s1", 2024)], CHANNEL: [_video("v1", 2024), _video("s1", 2024)]}

    _index(session, shorts, links_source)
    _index(session, main, links_source)

    assert _held(session) == {"s1": ("a-channel-shorts", "ep.S2024E01"), "v1": ("a-channel", "ep.S2024E01")}


def test_a_video_moves_to_the_collection_higher_in_the_channels_order_until_it_has_a_file(links_source, session):
    main, shorts = _channel_collections(session)
    links_source.links = {CHANNEL: [_video("v1", 2024), _video("s1", 2024, 2)]}
    _index(session, main, links_source)
    assert _held(session)["s1"] == ("a-channel", "ep.S2024E02")

    links_source.links[SHORTS] = [_video("s1", 2024, 2)]
    _index(session, shorts, links_source)

    assert _held(session) == {"v1": ("a-channel", "ep.S2024E01"), "s1": ("a-channel-shorts", "ep.S2024E01")}
