"""Link seasons: a collection of a creator's whole channel whose playlists, or an artist's albums, are its seasons.

Each link season is a link whose videos go to its season, but only the videos the collection itself lists.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import select

from sources import Feature, ItemRef, SectionKind, SectionRef, Site
from test_ytdlp_collections import ListedSource, _video, session  # noqa: F401

CHANNEL = "https://seasons.example/@creator/videos"


def _list(ref: str, title: str) -> SectionRef:
    return SectionRef(ref, f"https://seasons.example/playlist?list={ref}", title, SectionKind.LIST, kind_label="Playlist")


class ChannelSource(ListedSource):
    """A Site whose channels' playlists can be seasons."""

    id = "seasons"
    domains = ("seasons.example",)
    features = ListedSource.features | {Feature.CATALOGUE_REFRESH}
    sites = (Site("seasons", "Seasons", ("seasons.example",), link_seasons=True),)

    def __init__(self):
        super().__init__()
        self.lists: list[SectionRef] = []
        self.items: dict[str, tuple[str, ...]] = {}
        self.outside: dict[str, object] = {}

    def site_for(self, url):
        return self.sites[0]

    def is_channel_page(self, url):
        return url == CHANNEL

    def season_lists(self, url):
        return list(self.lists)

    def list_items(self, url):
        return tuple(ItemRef(slug, f"https://seasons.example/watch?v={slug}") for slug in self.items[url.rsplit("=", 1)[1]])

    def item_details(self, items):
        return {item.slug: self.outside.get(item.slug) for item in items}


@pytest.fixture
def source(monkeypatch):
    from backend.services import sites
    from sources import registry

    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    sites._site_of.cache_clear()
    yield registry.register(ChannelSource())
    sites._site_of.cache_clear()


def _collection(session, *, mode="all", loose="one_season", identifier="seasonal", url=CHANNEL, music=False):
    from backend.db.models import Collection

    collection = Collection(
        uuid="uuid-creator", slug="creator", source_key="seasons", title="The Creator", sharing_url=url,
        membership_level="FREE", type="music" if music else "series", episode_identifier=identifier,
        author_name="The Creator", author_slug="the-creator", link_seasons=mode, loose_videos=loose,
    )
    session.add(collection)
    session.commit()
    return collection


def _index(session, collection, source):
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    return index_listed_collection(session, collection_id=collection.id, source=source)


def _seasons(session):
    """Each season in order, with its number and the episodes in it."""
    from backend.db.models import Episode, Season

    session.expire_all()
    return [
        (season.name, season.season_number, sorted(
            session.scalars(select(Episode.source_slug).where(Episode.season_id == season.id)).all()
        ))
        for season in session.scalars(select(Season).order_by(Season.index))
    ]


def _give_files(session, *slugs):
    """Downloaded files for the episodes, which keep them where they are."""
    from backend.db.models import Episode
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.db.models import CollectionLocalMediaProfile
    from conftest import available_artifact

    if session.get(CollectionLocalMediaProfile, 1) is None:
        session.add(CollectionLocalMediaProfile(
            id=1, slug="videos", name="Videos", preferred_format="format_1080p",
            output_template="/downloads/{{ collection_title }}/{{ episode_title }}.ext",
        ))
        session.flush()
    for slug in slugs:
        episode_id = session.scalar(select(Episode.id).where(Episode.source_slug == slug))
        session.add(EpisodeMediaDownload(
            type="episode", media_item_id=episode_id, local_media_profile_id=1, file_path=f"/downloads/{slug}.mp4",
            **available_artifact(),
        ))
    session.commit()


def test_playlists_are_seasons_after_the_videos_in_none_and_take_only_the_channels_videos(source, session):
    source.videos = [_video("a", 2023, 3), _video("b", 2024, 5), _video("c", 2025, 2), _video("d", 2025, 6)]
    source.lists = [_list("PLnew", "Newest Builds"), _list("PLold", "First Builds")]
    # A playlist may hold another creator's video, which the collection does not list.
    source.items = {"PLnew": ("c", "elsewhere"), "PLold": ("a",)}
    collection = _collection(session)

    assert _index(session, collection, source) == 4

    # The videos in no playlist come first, then the playlists in the order their first video came out.
    assert _seasons(session) == [
        ("Videos", 1, ["b", "d"]), ("First Builds", 2, ["a"]), ("Newest Builds", 3, ["c"]),
    ]


def test_a_playlist_follows_the_year_it_started_in_with_a_season_per_year(source, session):
    source.videos = [_video("a", 2024, 3), _video("b", 2025, 2), _video("c", 2025, 9), _video("d", 2026, 1)]
    source.lists = [_list("PLtour", "The Tour")]
    source.items = {"PLtour": ("c",)}
    collection = _collection(session, loose="by_year")

    _index(session, collection, source)

    assert _seasons(session) == [
        ("2024", 1, ["a"]), ("2025", 2, ["b"]), ("The Tour", 3, ["c"]), ("2026", 4, ["d"]),
    ]


def test_a_video_in_two_playlists_goes_to_the_one_that_comes_first(source, session):
    source.videos = [_video("a", 2023), _video("b", 2024), _video("shared", 2025)]
    source.lists = [_list("PLlater", "Later"), _list("PLearly", "Early")]
    source.items = {"PLlater": ("b", "shared"), "PLearly": ("a", "shared")}
    collection = _collection(session)

    _index(session, collection, source)

    assert _seasons(session) == [("Early", 1, ["a", "shared"]), ("Later", 2, ["b"])]


def test_a_video_with_files_stays_until_it_is_moved_to_where_it_belongs(source, session):
    from backend.db.models import Episode
    from backend.services.link_seasons import belongs_elsewhere, move_to_where_it_belongs

    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session, identifier="seasonal")
    _index(session, collection, source)
    _give_files(session, "b")

    # The channel adds the downloaded video to its playlist.
    source.items = {"PLone": ("a", "b")}
    _index(session, collection, source)
    assert _seasons(session) == [("Videos", 1, ["b"]), ("One", 2, ["a"])]

    episode = session.scalar(select(Episode).where(Episode.source_slug == "b"))
    assert belongs_elsewhere(session, episode).link.title == "One"
    assert move_to_where_it_belongs(session, episode)
    session.commit()
    # The season it left is empty now, and goes.
    assert _seasons(session) == [("One", 1, ["a", "b"])]
    session.expire_all()
    assert session.scalar(select(Episode.episode_identifier).where(Episode.source_slug == "b")).startswith("ep.S01E")
    assert belongs_elsewhere(session, session.scalar(select(Episode).where(Episode.source_slug == "b"))) is None


def test_a_new_playlist_waits_for_the_users_choice_when_only_selected_ones_are_seasons(source, session):
    from backend.db.models import LinkSeason, NotificationEvent

    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",), "PLtwo": ("b",)}
    collection = _collection(session, mode="selected")
    _index(session, collection, source)

    source.lists = [_list("PLtwo", "Two"), _list("PLone", "One")]
    _index(session, collection, source)

    session.expire_all()
    assert {link.ref: (link.enabled, link.status) for link in session.scalars(select(LinkSeason))} == {
        "PLone": (True, "known"), "PLtwo": (False, "new"),
    }
    event = session.scalar(select(NotificationEvent))
    assert (event.title, event.url) == ("New playlist for The Creator", f"/edit-collection/{collection.id}?seasons=1")
    assert _seasons(session) == [("Videos", 1, ["b"]), ("One", 2, ["a"])]


def test_an_artists_albums_are_named_as_music(source, session):
    source.videos = [_video("t1", 2024), _video("t2", 2024, 2)]
    source.lists = [_list("PLalbum", "Harp")]
    source.items = {"PLalbum": ("t1",)}
    collection = _collection(session, music=True)

    _index(session, collection, source)

    assert _seasons(session) == [("Singles", 1, ["t2"]), ("Harp", 2, ["t1"])]


def test_a_single_playlist_is_no_channel_and_keeps_a_season_per_year(source, session):
    source.videos = [_video("a", 2024)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session, url="https://seasons.example/playlist?list=PLone")

    _index(session, collection, source)

    assert _seasons(session) == [("2024", 2024, ["a"])]


def test_the_user_renames_and_orders_the_seasons_and_a_new_one_goes_last(source, session):
    from backend.api.endpoints.collections.seasons.service import seasons_view, update_seasons
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction
    from backend.db.models import Episode

    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session)
    _index(session, collection, source)

    view = seasons_view(session, "creator")
    session.rollback()
    assert (view.names.one, view.names.loose_season, view.link_seasons_offered) == ("playlist", "Videos", True)
    videos, one = view.seasons
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": one.id, "name": "The One"}, {"id": videos.id, "name": "Uploads"}], custom_season_order=True,
        link_seasons="all", loose_videos="one_season",
    )
    run_write_transaction(lambda s: update_seasons(s, "creator", body))

    assert _seasons(session) == [("The One", 1, ["a"]), ("Uploads", 2, ["b"])]
    # Episodes without files follow their season's new number.
    assert session.scalar(select(Episode.episode_identifier).where(Episode.source_slug == "b")).startswith("ep.S02E")

    source.videos.append(_video("c", 2026))
    source.lists = [_list("PLtwo", "Two"), *source.lists]
    source.items["PLtwo"] = ("c",)
    _index(session, collection, source)
    assert _seasons(session) == [("The One", 1, ["a"]), ("Uploads", 2, ["b"]), ("Two", 3, ["c"])]


def test_turning_link_seasons_off_puts_the_videos_back_in_a_season_per_year(source, session):
    from backend.api.endpoints.collections.seasons.service import update_seasons
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction
    from backend.db.models import Season

    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session)
    _index(session, collection, source)

    seasons = session.scalars(select(Season).order_by(Season.index)).all()
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": season.id, "name": season.name} for season in seasons], custom_season_order=False,
        link_seasons="off",
    )
    session.rollback()
    run_write_transaction(lambda s: update_seasons(s, "creator", body))

    assert [(name, episodes) for name, _number, episodes in _seasons(session) if episodes] == [("2024", ["a"]), ("2025", ["b"])]


def test_only_a_whole_channel_can_turn_link_seasons_on(source, session):
    from backend.api.endpoints.collections.seasons.service import update_seasons
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction
    from backend.services.errors import ServiceError

    _collection(session, mode="off", url="https://seasons.example/playlist?list=PLone")
    body = CollectionSeasonsAPIUpdate(seasons=[], custom_season_order=False, link_seasons="all")

    with pytest.raises(ServiceError) as refused:
        run_write_transaction(lambda s: update_seasons(s, "creator", body))
    assert refused.value.field == "link_seasons"


def test_renaming_files_with_season_folders_moves_downloaded_videos_to_their_playlist(source, session):
    from backend.db.models import Episode
    from backend.services.link_seasons import place_in_link_seasons
    from backend.services.season_order import match_seasons_of_downloaded

    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session)
    _index(session, collection, source)
    _give_files(session, "b")
    source.items = {"PLone": ("a", "b")}
    _index(session, collection, source)

    from backend.db.models import Collection

    collection = session.get(Collection, collection.id)
    place_in_link_seasons(session, collection, with_files=True)
    match_seasons_of_downloaded(session, collection)
    session.commit()

    assert _seasons(session) == [("One", 1, ["a", "b"])]
    assert session.scalar(select(Episode.episode_identifier).where(Episode.source_slug == "b")).startswith("ep.S01E")


def test_a_site_can_name_its_link_seasons_itself(source, monkeypatch, session):
    from backend.services.link_seasons import link_season_names
    from sources import LinkSeasonNames

    monkeypatch.setattr(type(source), "sites", (replace(source.sites[0], link_season_names=LinkSeasonNames("set", "sets", "Loose")),))
    from backend.services import sites

    sites._site_of.cache_clear()
    collection = _collection(session)
    assert link_season_names(collection) == LinkSeasonNames("set", "sets", "Loose")
    collection.type = "music"
    assert link_season_names(collection) == LinkSeasonNames("album", "albums", "Singles")


def test_a_link_season_keeps_its_sites_order(source, session):
    from backend.api.endpoints.episodes.service import _episode_view_stmt
    from backend.db.models import Episode, Season
    from backend.types.collection_types import EpisodeOrder

    source.videos = [_video("a", 2023), _video("b", 2024), _video("c", 2025)]
    source.lists = [_list("PLmix", "Mix")]
    # The playlist puts its newest video first.
    source.items = {"PLmix": ("c", "a", "b")}
    collection = _collection(session)

    _index(session, collection, source)

    session.expire_all()
    numbered = dict(session.execute(select(Episode.source_slug, Episode.episode_identifier)).all())
    assert numbered == {"c": "ep.S01E01", "a": "ep.S01E02", "b": "ep.S01E03"}
    season = session.scalar(select(Season))
    shown = session.execute(_episode_view_stmt("creator", season_id=season.id, order=EpisodeOrder.OLDEST_FIRST)).all()
    assert [row.slug for row in shown] == [
        session.scalar(select(Episode.slug).where(Episode.source_slug == slug)) for slug in ("c", "a", "b")
    ]

    # The playlist is rearranged, and a video with files keeps its number while the others go around it.
    _give_files(session, "a")
    source.items = {"PLmix": ("b", "c", "a")}
    _index(session, collection, source)
    session.expire_all()
    numbered = dict(session.execute(select(Episode.source_slug, Episode.episode_identifier)).all())
    assert numbered == {"b": "ep.S01E01", "c": "ep.S01E03", "a": "ep.S01E02"}


def test_an_imported_channel_keeps_the_other_programs_seasons_for_its_playlists_and_other_videos(source, session):
    from backend.services.imports import _add_link_seasons
    from importer.contract import CollectionPlan, PlaylistSeasonPlan

    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session, mode="off")
    plan = CollectionPlan(
        external_id="subscription:creator", url=CHANNEL, title="The Creator",
        link_seasons=(PlaylistSeasonPlan("https://seasons.example/playlist?list=PLone", "Builds", 2),),
        loose_season=PlaylistSeasonPlan(CHANNEL, "Uploads", 1),
    )
    assert _add_link_seasons(session, collection, plan) == 1
    session.commit()

    _index(session, collection, source)

    assert _seasons(session) == [("Uploads", 1, ["b"]), ("Builds", 2, ["a"])]


def test_an_artists_albums_follow_the_artists_order_and_can_be_reordered(source, session):
    from backend.api.endpoints.collections.seasons.service import update_seasons
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction
    from backend.db.models import Season

    source.videos = [_video("old", 2020), _video("new", 2025), _video("single", 2024)]
    # The artist lists their older album first, the way they arranged their page.
    source.lists = [_list("PLold", "Debut"), _list("PLnew", "Latest")]
    source.items = {"PLold": ("old",), "PLnew": ("new",)}
    collection = _collection(session, music=True)

    _index(session, collection, source)
    assert _seasons(session) == [("Singles", 1, ["single"]), ("Debut", 2, ["old"]), ("Latest", 3, ["new"])]

    seasons = session.scalars(select(Season).order_by(Season.index)).all()
    singles, debut, latest = seasons
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": x.id, "name": x.name} for x in (latest, debut, singles)], custom_season_order=True,
        link_seasons="all",
    )
    session.rollback()
    run_write_transaction(lambda s: update_seasons(s, "creator", body))
    assert [name for name, _number, _episodes in _seasons(session)] == ["Latest", "Debut", "Singles"]


def test_videos_of_other_channels_in_a_playlist_join_the_collection_when_it_adds_them(source, session):
    from backend.db.models import Episode

    source.videos = [_video("a", 2024)]
    source.lists = [_list("PLcollab", "Collabs")]
    source.items = {"PLcollab": ("guest", "a")}
    source.outside = {"guest": _video("guest", 2023)}
    collection = _collection(session)
    collection.outside_videos = "add"
    session.commit()

    _index(session, collection, source)

    assert _seasons(session) == [("Collabs", 1, ["a", "guest"])]
    flags = dict(session.execute(select(Episode.source_slug, Episode.from_link_season)).all())
    assert flags == {"a": False, "guest": True}

    # The playlist drops the guest's video: without files it leaves the collection at once.
    source.items = {"PLcollab": ("a",)}
    _index(session, collection, source)
    assert _seasons(session) == [("Collabs", 1, ["a"])]


def test_a_video_from_outside_with_files_leaves_with_its_files(source, session, monkeypatch):
    from backend.api.endpoints.collections.seasons.service import seasons_view, update_seasons
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction
    from backend.db.models import Episode, LinkSeason, Season
    from task_manager.tasks.workers.remove_left_episodes import service as worker

    queued = []
    monkeypatch.setattr(
        "task_manager.scheduler.transactional.queue_task_after_commit",
        lambda s, **kwargs: queued.append(kwargs),
    )
    deleted = []
    monkeypatch.setattr(worker, "delete_episode_download_artifact", lambda s, download: deleted.append(download.file_path))
    monkeypatch.setattr(worker, "cancel_active_download_attempts", lambda s, downloads, reason: None)

    source.videos = [_video("a", 2024)]
    source.lists = [_list("PLcollab", "Collabs")]
    source.items = {"PLcollab": ("guest", "a")}
    source.outside = {"guest": _video("guest", 2023)}
    collection = _collection(session)
    collection.outside_videos = "add"
    session.commit()
    _index(session, collection, source)
    _give_files(session, "guest")

    view = seasons_view(session, "creator")
    session.rollback()
    (playlist,) = view.playlists
    assert (playlist.leaving_count, playlist.leaving_with_files) == (1, 1)
    assert (view.outside_count, view.outside_with_files) == (1, 1)

    # Turning the playlist off: the guest's video leaves, the channel's own one goes where a new video would.
    seasons = session.scalars(select(Season).order_by(Season.index)).all()
    link_id = session.scalar(select(LinkSeason.id))
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": x.id, "name": x.name} for x in seasons], custom_season_order=False,
        link_seasons="selected", outside_videos="add", playlists=[{"id": link_id, "enabled": False}],
    )
    session.rollback()
    run_write_transaction(lambda s: update_seasons(s, "creator", body))
    assert queued == [{"def_key": "remove_left_episodes", "resource_type": "collection", "resource_id": collection.id}]

    assert worker.run_remove_left_episodes(session, collection_id=collection.id) == 1
    assert deleted == ["/downloads/guest.mp4"]
    session.expire_all()
    assert session.scalars(select(Episode.source_slug)).all() == ["a"]
    assert _seasons(session) == [("Videos", 1, ["a"])]


def test_the_downloaded_videos_of_a_playlist_turned_off_move_where_new_videos_would_go(source, session, monkeypatch):
    from backend.api.endpoints.collections.seasons import service
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction
    from backend.db.models import Episode, LinkSeason, Season

    moved = []
    monkeypatch.setattr(service, "queue_season_folder_moves", lambda s, collection, ids: moved.append(ids))
    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session, mode="selected", loose="by_year")
    _index(session, collection, source)
    _give_files(session, "a")
    assert _seasons(session) == [("One", 1, ["a"]), ("2025", 2, ["b"])]

    seasons = session.scalars(select(Season).order_by(Season.index)).all()
    link_id = session.scalar(select(LinkSeason.id))
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": x.id, "name": x.name} for x in seasons], custom_season_order=False,
        link_seasons="selected", loose_videos="by_year", playlists=[{"id": link_id, "enabled": False}],
    )
    session.rollback()
    run_write_transaction(lambda s: update_seasons_call(service, s, body))

    episode_a = session.scalar(select(Episode).where(Episode.source_slug == "a"))
    assert moved == [[episode_a.id]]
    assert _seasons(session) == [("2024", 1, ["a"]), ("2025", 2, ["b"])]
    assert session.scalar(select(Episode.episode_identifier).where(Episode.source_slug == "a")).startswith("ep.S01E")


def update_seasons_call(service, s, body):
    return service.update_seasons(s, "creator", body)


def test_an_imported_single_video_is_a_season_of_its_own_and_joins_the_collection(source, session):
    from backend.services.imports import _add_link_seasons
    from importer.contract import CollectionPlan, PlaylistSeasonPlan

    source.videos = [_video("a", 2024)]
    source.items = {"special": ("special",)}
    source.outside = {"special": _video("special", 2023)}
    collection = _collection(session, mode="off")
    plan = CollectionPlan(
        external_id="subscription:creator", url=CHANNEL, title="The Creator",
        link_seasons=(PlaylistSeasonPlan("https://seasons.example/watch?v=special", "Specials", 0),),
        loose_season=PlaylistSeasonPlan(CHANNEL, "Videos", 1),
    )
    assert _add_link_seasons(session, collection, plan) == 1
    session.commit()
    assert collection.outside_videos == "add"

    _index(session, collection, source)

    assert _seasons(session) == [("Videos", 1, ["a"]), ("Specials", 0, ["special"])]


def test_ytdlp_lists_a_playlist_in_its_order_and_a_single_video_as_itself(monkeypatch):
    from sources import get_source
    from sources import ytdlp_runner as runner

    listings = {
        "https://www.youtube.com/playlist?list=PLx": {"_type": "playlist", "entries": [
            {"id": "b2", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=b2"}, {"id": "a1", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=a1"},
            {"id": "b2", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=b2"},
        ]},
        "https://www.youtube.com/watch?v=one": {"id": "one", "extractor_key": "Youtube", "webpage_url": "https://www.youtube.com/watch?v=one"},
    }
    monkeypatch.setattr(runner, "run_json", lambda *args, cookies=None: listings[args[-1]])
    source = get_source("ytdlp")

    assert [item.slug for item in source.list_items("https://www.youtube.com/playlist?list=PLx")] == ["b2", "a1"]
    assert [item.slug for item in source.list_items("https://www.youtube.com/watch?v=one")] == ["one"]


def test_a_downloaded_video_the_creator_takes_out_of_a_playlist_stays_until_the_user_lets_it_go(source, session, monkeypatch):
    from backend.api.endpoints.media_downloads.service import get_keep_questions
    from backend.db.core import run_write_transaction
    from backend.db.models import Episode
    from backend.services.removed_downloads import answer_keep_question
    from task_manager.tasks.workers.remove_left_episodes import service as worker

    queued = []
    monkeypatch.setattr(
        "task_manager.scheduler.transactional.queue_task_after_commit",
        lambda s, **kwargs: queued.append(kwargs),
    )
    deleted = []
    monkeypatch.setattr(worker, "delete_episode_download_artifact", lambda s, download: deleted.append(download.file_path))
    monkeypatch.setattr(worker, "cancel_active_download_attempts", lambda s, downloads, reason: None)

    source.videos = [_video("a", 2024)]
    source.lists = [_list("PLcollab", "Collabs")]
    source.items = {"PLcollab": ("guest", "a", "other")}
    source.outside = {"guest": _video("guest", 2023), "other": _video("other", 2023)}
    collection = _collection(session)
    collection.outside_videos = "add"
    session.commit()
    _index(session, collection, source)
    _give_files(session, "guest")

    # The creator takes both guests' videos out of the playlist.
    source.items = {"PLcollab": ("a",)}
    _index(session, collection, source)

    # The one without files leaves; the downloaded one stays, marked removed, nothing is deleted, and Home asks.
    session.expire_all()
    assert sorted(session.scalars(select(Episode.source_slug)).all()) == ["a", "guest"]
    guest = session.scalar(select(Episode).where(Episode.source_slug == "guest"))
    assert guest.removed_from_source
    assert queued == []
    (question,) = get_keep_questions(session)
    assert (question.episode_title, question.left_link) == ("Video guest", "Collabs")
    assert worker.run_remove_left_episodes(session, collection_id=collection.id) == 0
    assert deleted == []
    session.rollback()

    # Don't keep lets it go, files and all.
    run_write_transaction(lambda s: answer_keep_question(s, [guest.id], keep=False))
    assert queued == [{"def_key": "remove_left_episodes", "resource_type": "collection", "resource_id": collection.id}]
    assert worker.run_remove_left_episodes(session, collection_id=collection.id) == 1
    assert deleted == ["/downloads/guest.mp4"]
    session.expire_all()
    assert session.scalars(select(Episode.source_slug)).all() == ["a"]


def test_a_kept_video_stays_and_is_back_when_the_playlist_lists_it_again(source, session):
    from backend.db.core import run_write_transaction
    from backend.db.models import Episode
    from backend.services.removed_downloads import answer_keep_question

    source.videos = [_video("a", 2024)]
    source.lists = [_list("PLcollab", "Collabs")]
    source.items = {"PLcollab": ("guest",)}
    source.outside = {"guest": _video("guest", 2023)}
    collection = _collection(session)
    collection.outside_videos = "add"
    session.commit()
    _index(session, collection, source)
    _give_files(session, "guest")
    source.items = {"PLcollab": ()}
    _index(session, collection, source)
    guest_id = session.scalar(select(Episode.id).where(Episode.source_slug == "guest"))
    session.rollback()
    run_write_transaction(lambda s: answer_keep_question(s, [guest_id], keep=True))

    _index(session, collection, source)
    session.expire_all()
    assert session.get(Episode, guest_id).removed_from_source

    source.items = {"PLcollab": ("guest",)}
    _index(session, collection, source)
    session.expire_all()
    assert not session.get(Episode, guest_id).removed_from_source
    assert _seasons(session) == [("Videos", 1, ["a"]), ("Collabs", 2, ["guest"])]
