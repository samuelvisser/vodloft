"""Link seasons: a collection of a creator's whole channel whose playlists, or an artist's albums, are its seasons.

Each link season is a link whose videos go to its season, but only the videos the collection itself lists.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import select

from sources import LIST_TYPE, Feature, ItemRef, Names, SectionKind, SectionRef, SectionType, Site
from test_ytdlp_collections import ListedSource, _video, session  # noqa: F401

CREATOR = "https://seasons.example/@creator/videos"
PLAYLISTS = SectionType(LIST_TYPE, SectionKind.LIST, Names("playlist", "playlists"))


def _list(ref: str, title: str) -> SectionRef:
    return SectionRef(ref, f"https://seasons.example/playlist?list={ref}", PLAYLISTS, title)


class CreatorSource(ListedSource):
    """A Site whose creators' playlists can be seasons."""

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

    def is_creator_page(self, url):
        return url == CREATOR

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
    yield registry.register(CreatorSource())
    sites._site_of.cache_clear()


def _collection(session, *, mode="all", loose="one_season", identifier="seasonal", url=CREATOR, music=False, channel_season="unlisted"):
    from backend.db.models import Collection

    collection = Collection(
        uuid="uuid-creator", slug="creator", source_key="seasons", title="The Creator", sharing_url=url,
        membership_level="FREE", type="music" if music else "series", episode_identifier=identifier,
        author_name="The Creator", author_slug="the-creator", link_seasons=mode, loose_videos=loose,
        channel_season=channel_season,
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


def test_playlists_are_seasons_after_the_videos_in_none_and_take_only_the_creators_videos(source, session):
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
    # A playlist's season came from a list, a season per year from VODLoft.
    from backend.db.models import Season
    assert {season.name: season.origin for season in session.query(Season)} == {
        "2024": "vodloft", "2025": "vodloft", "The Tour": "list", "2026": "vodloft",
    }


def test_a_video_in_two_playlists_goes_to_the_one_that_comes_first(source, session):
    source.videos = [_video("a", 2023), _video("b", 2024), _video("shared", 2025)]
    source.lists = [_list("PLlater", "Later"), _list("PLearly", "Early")]
    source.items = {"PLlater": ("b", "shared"), "PLearly": ("a", "shared")}
    collection = _collection(session)

    _index(session, collection, source)

    assert _seasons(session) == [("Early", 1, ["a", "shared"]), ("Later", 2, ["b"])]


def test_a_video_with_files_stays_until_it_is_moved_to_where_it_belongs(source, session):
    from backend.db.models import Episode
    from backend.services.link_seasons import belongs_elsewhere, moved_episodes
    from backend.db.core import run_write_transaction
    from backend.services.reconcile import ReconcileScope, reconcile

    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session, identifier="seasonal")
    _index(session, collection, source)
    _give_files(session, "b")

    # The creator adds the downloaded video to its playlist.
    source.items = {"PLone": ("a", "b")}
    _index(session, collection, source)
    assert _seasons(session) == [("Videos", 1, ["b"]), ("One", 2, ["a"])]

    episode = session.scalar(select(Episode).where(Episode.source_slug == "b"))
    assert belongs_elsewhere(session, episode).link.title == "One"
    # The collection view marks it Moved.
    assert [moved.source_slug for moved in moved_episodes(session, collection)] == ["b"]
    episode_id = episode.id
    session.commit()
    run_write_transaction(lambda w: reconcile(w, ReconcileScope.of_episode(w.get(Episode, episode_id)), renumber={}))
    session.expire_all()
    # The season it left is empty now, and goes.
    assert _seasons(session) == [("One", 1, ["a", "b"])]
    session.expire_all()
    assert session.scalar(select(Episode.episode_identifier).where(Episode.source_slug == "b")).startswith("ep.S01E")
    assert belongs_elsewhere(session, session.scalar(select(Episode).where(Episode.source_slug == "b"))) is None
    assert moved_episodes(session, session.get(type(collection), collection.id)) == []


def test_a_new_playlist_waits_for_the_users_choice_when_only_selected_ones_are_seasons(source, session):
    from backend.db.models import CollectionList, NotificationEvent

    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",), "PLtwo": ("b",)}
    collection = _collection(session, mode="selected")
    collection.new_lists = {LIST_TYPE: "ask"}
    session.commit()
    _index(session, collection, source)

    source.lists = [_list("PLtwo", "Two"), _list("PLone", "One")]
    _index(session, collection, source)

    session.expire_all()
    assert {link.ref: (link.enabled, link.status) for link in session.scalars(select(CollectionList))} == {
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


def test_a_single_playlist_is_no_creator_and_keeps_a_season_per_year(source, session):
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
    assert ([t.names.singular for t in view.list_types], view.loose_season, view.link_seasons_offered) == (["playlist"], "Videos", True)
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


def test_a_contents_only_list_adds_its_videos_to_the_other_seasons_and_can_be_a_season_again(source, session):
    from backend.api.endpoints.collections.seasons.service import seasons_view, update_seasons
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction

    source.videos = [_video("a", 2024), _video("b", 2025), _video("c", 2025, 3)]
    source.lists = [_list("PLone", "One"), _list("PLtwo", "Two")]
    source.items = {"PLone": ("a",), "PLtwo": ("c",)}
    collection = _collection(session)
    _index(session, collection, source)
    assert [(name, episodes) for name, _number, episodes in _seasons(session)] == [
        ("Videos", ["b"]), ("One", ["a"]), ("Two", ["c"]),
    ]

    def save(as_season: bool):
        view = seasons_view(session, "creator")
        session.rollback()
        one = next(playlist for playlist in view.playlists if playlist.ref == "PLone")
        body = CollectionSeasonsAPIUpdate(
            seasons=[{"id": season.id, "name": season.name} for season in view.seasons], custom_season_order=False,
            link_seasons="all", playlists=[{"id": one.id, "enabled": True, "as_season": as_season}],
        )
        run_write_transaction(lambda s: update_seasons(s, "creator", body))
        return view

    save(False)
    assert [(name, episodes) for name, _number, episodes in _seasons(session) if episodes] == [
        ("Videos", ["a", "b"]), ("Two", ["c"]),
    ]
    assert not next(playlist for playlist in seasons_view(session, "creator").playlists if playlist.ref == "PLone").as_season
    session.rollback()

    save(True)
    assert [(name, episodes) for name, _number, episodes in _seasons(session) if episodes] == [
        ("Videos", ["b"]), ("One", ["a"]), ("Two", ["c"]),
    ]


def test_a_collection_of_only_its_lists_has_no_other_seasons_for_a_contents_only_list(source, session):
    from backend.api.endpoints.collections.seasons.service import seasons_view, update_seasons
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction
    from backend.services.errors import ServiceError

    source.videos = [_video("a", 2024)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session)
    _index(session, collection, source)
    view = seasons_view(session, "creator")
    session.rollback()
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": season.id, "name": season.name} for season in view.seasons], custom_season_order=False,
        link_seasons="all", outside_videos="only", playlists=[{"id": view.playlists[0].id, "enabled": True, "as_season": False}],
    )
    with pytest.raises(ServiceError, match="no other seasons"):
        run_write_transaction(lambda s: update_seasons(s, "creator", body))


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


def test_only_a_whole_creator_can_turn_link_seasons_on(source, session):
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
    from backend.services.link_seasons import section_list_names, loose_season_name
    from sources import Names, SectionKind, SectionType

    monkeypatch.setattr(type(source), "sites", (replace(source.sites[0], section_types=(
        SectionType("set", SectionKind.LIST, Names("set", "sets")), SectionType("mix", SectionKind.LIST, Names("mix", "mixes")),
    ), loose_season="Loose"),))
    from backend.services import sites

    sites._site_of.cache_clear()
    collection = _collection(session)
    assert (section_list_names(collection), loose_season_name(collection)) == (Names("set or mix", "sets and mixes"), "Loose")
    collection.type = "music"
    assert loose_season_name(collection) == "Singles"


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


def test_an_imported_creator_keeps_the_other_programs_seasons_for_its_playlists_and_other_videos(source, session):
    from backend.services.imports import _add_link_seasons
    from importer.contract import CollectionPlan, PlaylistSeasonPlan

    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session, mode="off")
    plan = CollectionPlan(
        external_id="subscription:creator", url=CREATOR, title="The Creator",
        link_seasons=(PlaylistSeasonPlan("https://seasons.example/playlist?list=PLone", "Builds", 2),),
        loose_season=PlaylistSeasonPlan(CREATOR, "Uploads", 1),
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


def test_videos_of_other_creators_in_a_playlist_join_the_collection_when_it_adds_them(source, session):
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
    from backend.db.models import Episode, CollectionList, Season
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

    # Turning the playlist off: the guest's video leaves, the creator's own one goes where a new video would.
    seasons = session.scalars(select(Season).order_by(Season.index)).all()
    link_id = session.scalar(select(CollectionList.id))
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
    from backend.db.models import Episode, CollectionList, Season

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
    link_id = session.scalar(select(CollectionList.id))
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


def test_a_season_of_a_list_left_over_while_link_seasons_were_off_empties_when_saved(source, session, monkeypatch):
    from backend.api.endpoints.collections.seasons import service
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection, CollectionList, Season

    monkeypatch.setattr(service, "queue_season_folder_moves", lambda s, collection, ids: None)
    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session, mode="selected", loose="by_year")
    _index(session, collection, source)
    _give_files(session, "a")
    # As the old creators left it: a season of a list that is off, in a collection whose playlists are off.
    session.get(Collection, collection.id).link_seasons = "off"
    session.scalar(select(CollectionList)).enabled = False
    session.commit()
    assert _seasons(session) == [("One", 1, ["a"]), ("2025", 2, ["b"])]

    seasons = session.scalars(select(Season).order_by(Season.index)).all()
    link_id = session.scalar(select(CollectionList.id))
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": x.id, "name": x.name} for x in seasons], custom_season_order=False,
        link_seasons="selected", loose_videos="by_year", playlists=[{"id": link_id, "enabled": False}],
    )
    session.rollback()
    run_write_transaction(lambda s: update_seasons_call(service, s, body))

    assert _seasons(session) == [("2024", 1, ["a"]), ("2025", 2, ["b"])]


def test_downloaded_videos_of_year_seasons_wait_for_the_move_after_a_save_puts_them_in_one_season(source, session, monkeypatch):
    from backend.api.endpoints.collections.seasons import service
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection, Season
    from backend.services.link_seasons import moved_episodes
    from backend.services.reconcile import ReconcileScope, reconcile

    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ()}
    collection = _collection(session, mode="selected", loose="by_year")
    _index(session, collection, source)
    _give_files(session, "a")
    assert _seasons(session) == [("2024", 2024, ["a"]), ("2025", 2025, ["b"])]

    seasons = session.scalars(select(Season).order_by(Season.index)).all()
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": x.id, "name": x.name} for x in seasons], custom_season_order=False,
        link_seasons="selected", loose_videos="one_season",
    )
    session.rollback()
    run_write_transaction(lambda s: update_seasons_call(service, s, body))

    # The video without files moved at once; the downloaded one waits for the Move dialog the save opens.
    assert _seasons(session) == [("Videos", 1, ["b"]), ("2024", 2, ["a"])]
    assert [episode.source_slug for episode in moved_episodes(session, session.get(Collection, collection.id))] == ["a"]
    session.rollback()
    run_write_transaction(lambda w: reconcile(w, ReconcileScope.of_collection(w.get(Collection, collection.id)), renumber={}))
    session.expire_all()
    assert _seasons(session) == [("Videos", 1, ["a", "b"])]


def test_the_channel_season_takes_its_new_name_when_it_holds_the_whole_channel(source, session, monkeypatch):
    from backend.api.endpoints.collections.seasons import service
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction
    from backend.db.models import Season

    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session, mode="selected", loose="one_season")
    _index(session, collection, source)
    view = service.seasons_view(session, "creator")
    session.rollback()
    loose = next(season for season in view.seasons if season.loose)
    assert loose.name == view.channel_season_names["unlisted"]

    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": x.id, "name": x.name} for x in view.seasons], custom_season_order=False,
        link_seasons="selected", loose_videos="one_season", channel_season="everything",
    )
    run_write_transaction(lambda s: update_seasons_call(service, s, body))

    assert session.get(Season, loose.id).name == view.channel_season_names["everything"]


def _remove(session, service, *names, **settings):
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction

    view = service.seasons_view(session, "creator")
    session.rollback()
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": x.id, "name": x.name} for x in view.seasons], custom_season_order=False,
        link_seasons=settings.pop("link_seasons", "selected"), loose_videos=settings.pop("loose_videos", "by_year"),
        playlists=[{"id": p.id, "enabled": p.enabled, "season_id": p.season_id} for p in view.playlists],
        removed_seasons=[x.id for x in view.seasons if x.name in names], **settings,
    )
    run_write_transaction(lambda s: update_seasons_call(service, s, body))
    session.expire_all()
    return view


def test_a_removed_season_per_year_comes_back_when_the_settings_put_its_videos_there(source, session, monkeypatch):
    from backend.api.endpoints.collections.seasons import service
    from backend.db.models import Season

    moved = []
    monkeypatch.setattr(service, "queue_season_folder_moves", lambda s, collection, ids: moved.append(ids))
    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = []
    source.items = {}
    collection = _collection(session, mode="selected", loose="by_year")
    _index(session, collection, source)
    _give_files(session, "a")
    view = _remove(session, service, "2024", "2025")
    assert all(season.removable for season in view.seasons)

    # Made again by the settings, with the same slugs; the downloaded video's files follow it.
    assert _seasons(session) == [("2024", 2024, ["a"]), ("2025", 2025, ["b"])]
    assert {season.id for season in session.scalars(select(Season))}.isdisjoint({x.id for x in view.seasons})
    assert len(moved) == 1

    # In one season instead, they go for good.
    _remove(session, service, "2024", "2025", loose_videos="one_season")
    assert [(name, episodes) for name, _number, episodes in _seasons(session)] == [("Videos", ["a", "b"])]


def test_a_removed_season_of_a_list_or_a_leftover_season_goes_to_the_seasons_the_settings_give(source, session, monkeypatch):
    from backend.api.endpoints.collections.seasons import service
    from backend.db.models import Episode, Season

    monkeypatch.setattr(service, "queue_season_folder_moves", lambda s, collection, ids: None)
    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session, mode="selected", loose="one_season")
    _index(session, collection, source)
    # A season no setting makes, as an older VODLoft left one.
    leftover = Season(collection_id=collection.id, index=99, slug="old", name="Old", season_number=9)
    session.add(leftover)
    session.flush()
    session.scalar(select(Episode).where(Episode.source_slug == "b")).season_id = leftover.id
    session.commit()

    _remove(session, service, "One", "Old", loose_videos="one_season")

    # The list is still a season, so its season is made again; the leftover's video goes to the channel season.
    assert [(name, episodes) for name, _number, episodes in _seasons(session)] == [("Videos", ["b"]), ("One", ["a"])]


def test_a_season_the_site_has_itself_is_not_removable(source, session):
    from backend.api.endpoints.collections.seasons import service
    from backend.db.models import Season
    from backend.services.errors import ServiceError
    from backend.types.season_types import SeasonOrigin

    source.videos = [_video("a", 2024)]
    source.lists = []
    source.items = {}
    collection = _collection(session, mode="selected", loose="one_season")
    _index(session, collection, source)
    session.add(Season(
        collection_id=collection.id, index=99, slug="season-1", name="Season 1", season_number=1,
        origin=SeasonOrigin.SITE.value,
    ))
    session.commit()

    view = service.seasons_view(session, "creator")
    session.rollback()
    assert {x.name: x.removable for x in view.seasons} == {"Videos": True, "Season 1": False}
    with pytest.raises(ServiceError):
        _remove(session, service, "Season 1", loose_videos="one_season")


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
        external_id="subscription:creator", url=CREATOR, title="The Creator",
        link_seasons=(PlaylistSeasonPlan("https://seasons.example/watch?v=special", "Specials", 0),),
        loose_season=PlaylistSeasonPlan(CREATOR, "Videos", 1),
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


class LinksSource(CreatorSource):
    """A Source that can hold a collection of only the links the user picks."""

    features = CreatorSource.features | {Feature.LINK_COLLECTIONS}

    def list_items(self, url):
        return tuple(ItemRef(slug, f"https://seasons.example/watch?v={slug}") for slug in self.items[url.rsplit("=", 1)[1]])


@pytest.fixture
def links_source(monkeypatch):
    from backend.services import sites
    from sources import registry

    # The only Source that can hold such a collection, so a new one is made with it.
    monkeypatch.setattr(registry, "_sources", {})
    sites._site_of.cache_clear()
    yield registry.register(LinksSource())
    sites._site_of.cache_clear()


def _update(session, slug="creator", **changes):
    from backend.api.endpoints.collections.seasons.service import seasons_view, update_seasons
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction

    view = seasons_view(session, slug)
    session.rollback()
    body = {
        "seasons": [{"id": season.id, "name": season.name} for season in view.seasons],
        "custom_season_order": view.custom_season_order, "link_seasons": view.link_seasons,
        "new_lists": {setting.key: setting.action for setting in view.new_lists}, "loose_videos": view.loose_videos,
        "outside_videos": view.outside_videos,
        "playlists": [{"id": playlist.id, "enabled": playlist.enabled} for playlist in view.playlists],
        **changes,
    }
    return run_write_transaction(lambda s: update_seasons(s, slug, CollectionSeasonsAPIUpdate(**body)))


def test_a_collection_that_holds_only_its_playlists_leaves_the_creators_other_videos_out(links_source, session):
    from backend.db.models import Episode

    source = links_source
    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLbest", "Best Of")]
    source.items = {"PLbest": ("a", "guest")}
    source.outside = {"a": _video("a", 2024), "guest": _video("guest", 2023)}
    collection = _collection(session, mode="all")
    collection.outside_videos = "only"
    session.commit()

    _index(session, collection, source)

    # No season of videos in no playlist: only what the playlist has, also another creator's video.
    assert _seasons(session) == [("Best Of", 1, ["a", "guest"])]
    assert all(session.scalars(select(Episode.from_link_season)).all())


def test_switching_to_only_the_playlists_removes_the_videos_none_of_them_has(links_source, session, monkeypatch):
    from backend.db.models import Episode

    queued = []
    monkeypatch.setattr(
        "task_manager.scheduler.transactional.queue_task_after_commit", lambda s, **kwargs: queued.append(kwargs),
    )
    source = links_source
    source.videos = [_video("a", 2024), _video("b", 2025), _video("c", 2025)]
    source.lists = [_list("PLbest", "Best Of")]
    source.items = {"PLbest": ("a",)}
    source.outside = {"a": _video("a", 2024)}
    collection = _collection(session)
    _index(session, collection, source)
    _give_files(session, "b", "a")

    view = _update(session, outside_videos="only")
    # Nothing leaves before the playlists are listed again.
    assert (view.outside_videos, view.only_leaving_count) == ("only", 0)
    assert sorted(session.scalars(select(Episode.source_slug)).all()) == ["a", "b", "c"]

    _index(session, collection, source)
    # The one without files leaves; the downloaded one stays until the user answers the Home page.
    session.expire_all()
    assert sorted(session.scalars(select(Episode.source_slug)).all()) == ["a", "b"]
    assert session.scalar(select(Episode.removed_from_source).where(Episode.source_slug == "b"))
    assert _seasons(session)[-1] == ("Best Of", 2, ["a"])


def test_an_empty_collection_takes_links_the_user_adds(links_source, session):
    from backend.api.endpoints.collections.seasons.service import AddedLink, save_added_link, seasons_view
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection
    from backend.services.collections import add_links_only_collection
    from backend.types.collection_types import CollectionType

    source = links_source
    source.items = {"PLmix": ("x", "y"), "PLmore": ("y", "z")}
    source.outside = {slug: _video(slug, 2024, month) for month, slug in enumerate(("x", "y", "z"), start=1)}
    slug = run_write_transaction(
        lambda s: add_links_only_collection(s, title="My Mix", collection_type=CollectionType.SERIES).slug,
    )
    session.expire_all()
    collection = session.scalar(select(Collection).where(Collection.slug == slug))
    assert (collection.sharing_url, collection.site_key, collection.source_key) == (None, None, "seasons")

    for ref, title in (("PLmix", "The Mix"), ("PLmore", "More")):
        link = AddedLink(ref, f"https://seasons.example/playlist?list={ref}", title, None, "seasons")
        run_write_transaction(lambda s, link=link: save_added_link(s, slug, link))
    view = seasons_view(session, slug)
    session.rollback()
    assert [(link.title, link.added_by_user) for link in view.playlists] == [("The Mix", True), ("More", True)]
    assert (view.has_own_link, view.lists_playlists, view.link_seasons_offered) == (False, False, True)

    _index(session, session.scalar(select(Collection).where(Collection.slug == slug)), source)
    # A video in both goes to the first.
    assert _seasons(session) == [("The Mix", 1, ["x", "y"]), ("More", 2, ["z"])]

    # Removing a link removes its videos with it.
    more = next(link for link in view.playlists if link.title == "More")
    _update(session, slug, removed_links=[more.id], playlists=[{"id": more.id, "enabled": True}])
    assert _seasons(session) == [("The Mix", 1, ["x", "y"])]


def test_a_collection_without_a_link_can_only_hold_its_playlists(links_source, session):
    from backend.db.core import run_write_transaction
    from backend.services.collections import add_links_only_collection
    from backend.services.errors import ServiceError
    from backend.types.collection_types import CollectionType

    run_write_transaction(lambda s: add_links_only_collection(s, title="Mix", collection_type=CollectionType.MUSIC))
    with pytest.raises(ServiceError) as refused:
        _update(session, "mix", outside_videos="add")
    assert refused.value.field == "outside_videos"


def test_an_imported_show_of_only_playlists_holds_them_in_the_other_programs_seasons(links_source, session):
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection
    from backend.services import imports
    from importer.contract import CollectionPlan, PlaylistSeasonPlan

    first = "https://seasons.example/playlist?list=PLfirst"
    plan = CollectionPlan(
        external_id="subscription:Mixed", url=first, title="Mixed", settings={"type": "series", "episode_identifier": "seasonal"},
        link_seasons=(PlaylistSeasonPlan(first, "Firsts", 1), PlaylistSeasonPlan("https://seasons.example/playlist?list=PLsecond", "Seconds", 2)),
        links_only=True,
    )
    slug = run_write_transaction(lambda s: imports._create_links_only_collection(s, plan).slug)

    collection = session.scalar(select(Collection).where(Collection.slug == slug))
    assert (collection.sharing_url, collection.outside_videos, collection.custom_season_order) == (None, "only", True)
    assert [(link.title, link.season.season_number) for link in sorted(collection.lists, key=lambda x: x.id)] == [
        ("Firsts", 1), ("Seconds", 2),
    ]


def _put_together(session, lists: dict[str, int | None]):
    """Save the Seasons dialog with each list, by ref, in the season of the list it names, or a season of its own."""
    from backend.api.endpoints.collections.seasons.service import seasons_view, update_seasons
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction

    view = seasons_view(session, "creator")
    session.rollback()
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": season.id, "name": season.name} for season in view.seasons],
        custom_season_order=view.custom_season_order, link_seasons=view.link_seasons, loose_videos=view.loose_videos,
        playlists=[
            {"id": playlist.id, "enabled": playlist.enabled, "season_id": lists.get(playlist.ref, playlist.season_id)}
            for playlist in view.playlists
        ],
    )
    return run_write_transaction(lambda s: update_seasons(s, "creator", body))


def _season_of(session, ref: str) -> int:
    from backend.db.models import CollectionList

    session.expire_all()
    return session.scalar(select(CollectionList.season_id).where(CollectionList.ref == ref))


def test_two_lists_share_one_season_with_the_first_lists_videos_first(source, session):
    from backend.db.models import Episode

    source.videos = [_video("a", 2023), _video("b", 2023, 6), _video("c", 2024), _video("d", 2024, 6), _video("e", 2025)]
    source.lists = [_list("PLtwo", "Cabin, Part 2"), _list("PLone", "Cabin, Part 1")]
    # Each playlist lists its videos newest first.
    source.items = {"PLone": ("b", "a"), "PLtwo": ("d", "c")}
    collection = _collection(session)
    _index(session, collection, source)
    assert _seasons(session) == [("Videos", 1, ["e"]), ("Cabin, Part 1", 2, ["a", "b"]), ("Cabin, Part 2", 3, ["c", "d"])]

    view = _put_together(session, {"PLtwo": _season_of(session, "PLone")})

    # The season keeps its name, and holds the videos of Part 1 in its order, then those of Part 2.
    assert _seasons(session) == [("Videos", 1, ["e"]), ("Cabin, Part 1", 2, ["a", "b", "c", "d"])]
    numbers = dict(session.execute(select(Episode.source_slug, Episode.episode_identifier)).all())
    assert [numbers[slug] for slug in ("b", "a", "d", "c")] == ["ep.S02E01", "ep.S02E02", "ep.S02E03", "ep.S02E04"]
    assert [season.list_titles for season in view.seasons] == [[], ["Cabin, Part 1", "Cabin, Part 2"]]

    # A new video of Part 2 goes to the season it shares.
    source.videos.append(_video("f", 2026))
    source.items["PLtwo"] = ("f", "d", "c")
    _index(session, collection, source)
    assert _seasons(session) == [("Videos", 1, ["e"]), ("Cabin, Part 1", 2, ["a", "b", "c", "d", "f"])]

    # A list given a season of its own again takes its videos along.
    _put_together(session, {"PLtwo": None})
    assert _seasons(session) == [("Videos", 1, ["e"]), ("Cabin, Part 1", 2, ["a", "b"]), ("Cabin, Part 2", 3, ["c", "d", "f"])]


def test_the_downloaded_videos_of_a_list_that_joins_another_season_move_with_their_files(source, session, monkeypatch):
    from backend.api.endpoints.collections.seasons import service
    from backend.db.models import Episode

    moved = []
    monkeypatch.setattr(service, "queue_season_folder_moves", lambda s, collection, ids: moved.append(ids))
    source.videos = [_video("a", 2023), _video("c", 2024)]
    source.lists = [_list("PLtwo", "Part 2"), _list("PLone", "Part 1")]
    source.items = {"PLone": ("a",), "PLtwo": ("c",)}
    collection = _collection(session)
    _index(session, collection, source)
    _give_files(session, "c")

    _put_together(session, {"PLtwo": _season_of(session, "PLone")})

    assert moved == [[session.scalar(select(Episode.id).where(Episode.source_slug == "c"))]]
    assert _seasons(session) == [("Part 1", 1, ["a", "c"])]


def test_a_list_only_joins_a_season_of_the_collections_lists(source, session):
    from backend.db.models import Season
    from backend.services.errors import ServiceError

    source.videos = [_video("a", 2023), _video("b", 2024)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session)
    _index(session, collection, source)
    videos = session.scalar(select(Season.id).where(Season.loose))

    with pytest.raises(ServiceError, match="can only join a season that holds one of the collection's lists"):
        _put_together(session, {"PLone": videos})


def test_lists_laid_out_by_year_still_decide_what_is_in(source, session):
    from backend.services.link_seasons import moved_episodes

    source.videos = [_video("a", 2023), _video("b", 2024), _video("c", 2024, 6), _video("d", 2025)]
    source.lists = [_list("PLtour", "The Tour")]
    source.items = {"PLtour": ("b", "a", "guest")}
    collection = _collection(session)
    _index(session, collection, source)
    _give_files(session, "d")
    assert _seasons(session) == [("Videos", 1, ["c", "d"]), ("The Tour", 2, ["a", "b"])]

    _update(session, list_layout="by_year")

    # The playlist's videos and the others share the year seasons; the other creator's video stays out. The
    # downloaded one stays where it is until it is moved, as with any season change.
    assert _seasons(session) == [("Videos", 1, ["d"]), ("2023", 2, ["a"]), ("2024", 3, ["b", "c"])]
    assert [episode.source_slug for episode in moved_episodes(session, collection)] == ["d"]

    _update(session, list_layout="season_each")
    assert _seasons(session) == [("Videos", 1, ["c", "d"]), ("The Tour", 2, ["a", "b"])]


def test_an_episode_of_a_list_laid_out_by_year_names_its_list_in_templates(source, session):
    from backend.db.models import Episode
    from backend.utils.output_template import _creator_values

    source.videos = [_video("a", 2023), _video("b", 2024)]
    source.lists = [_list("PLtour", "The Tour")]
    source.items = {"PLtour": ("a",)}
    collection = _collection(session)
    _index(session, collection, source)
    _update(session, list_layout="by_year")
    session.expire_all()

    titles = {
        slug: _creator_values(session.scalar(select(Episode).where(Episode.source_slug == slug)))["section_title"]
        for slug in ("a", "b")
    }
    # The video in no list is of the feed that brought it.
    assert titles == {"a": "The Tour", "b": "Videos"}


def test_the_list_of_seasons_says_when_each_ones_newest_episode_came_out(source, session):
    """A collection page opens on the season with the newest episode, such as Videos beside a season per year that
    only holds downloaded videos waiting to move."""
    from datetime import datetime, timezone

    from backend.api.endpoints.seasons.service import get_seasons_list

    source.videos = [_video("a", 2023, 1), _video("b", 2024, 2), _video("c", 2026, 11)]
    source.lists = [_list("PLone", "Builds")]
    source.items = {"PLone": ("a", "b")}
    collection = _collection(session)
    _index(session, collection, source)

    newest = {season.name: season.newest_published_at for season in get_seasons_list(session, collection.slug)}
    assert newest == {
        "Builds": datetime(2024, 2, 1, tzinfo=timezone.utc), "Videos": datetime(2026, 11, 1, tzinfo=timezone.utc),
    }


def _switch_off(session, *refs: str):
    """Save the Seasons dialog with only the lists it names switched off."""
    from backend.api.endpoints.collections.seasons.service import seasons_view, update_seasons
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction

    view = seasons_view(session, "creator")
    session.rollback()
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": season.id, "name": season.name} for season in view.seasons],
        custom_season_order=view.custom_season_order, link_seasons="selected", loose_videos=view.loose_videos,
        playlists=[
            {"id": playlist.id, "enabled": playlist.ref not in refs, "season_id": playlist.season_id}
            for playlist in view.playlists
        ],
    )
    return run_write_transaction(lambda s: update_seasons(s, "creator", body))


def test_a_shared_season_stays_until_every_list_in_it_is_switched_off(source, session):
    source.videos = [_video("a", 2023), _video("b", 2023, 6), _video("c", 2024), _video("e", 2025)]
    source.lists = [_list("PLtwo", "Cabin, Part 2"), _list("PLone", "Cabin, Part 1")]
    source.items = {"PLone": ("b", "a"), "PLtwo": ("c",)}
    collection = _collection(session)
    _index(session, collection, source)
    _put_together(session, {"PLtwo": _season_of(session, "PLone")})
    assert _seasons(session) == [("Videos", 1, ["e"]), ("Cabin, Part 1", 2, ["a", "b", "c"])]

    # The list the season is named after goes; the season stays for the list still in it.
    _switch_off(session, "PLone")
    assert _seasons(session) == [("Videos", 1, ["a", "b", "e"]), ("Cabin, Part 1", 2, ["c"])]

    # With its last list off, the season is deleted.
    _switch_off(session, "PLone", "PLtwo")
    assert _seasons(session) == [("Videos", 1, ["a", "b", "c", "e"])]


def test_the_preview_shows_the_seasons_a_save_would_leave_and_saves_nothing(source, session):
    from backend.api.endpoints.collections.seasons.service import preview_seasons, seasons_view
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction

    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = []
    source.items = {}
    collection = _collection(session, mode="selected", loose="by_year")
    _index(session, collection, source)
    before = _seasons(session)
    assert before == [("2024", 2024, ["a"]), ("2025", 2025, ["b"])]

    view = seasons_view(session, "creator")
    session.rollback()
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": x.id, "name": x.name} for x in view.seasons], custom_season_order=False,
        link_seasons="selected", loose_videos="one_season", playlists=[],
    )
    preview = run_write_transaction(lambda s: preview_seasons(s, "creator", body))

    assert [(season.name, season.episode_count) for season in preview.seasons] == [("Videos", 2)]
    assert _seasons(session) == before


def test_listing_a_collection_again_after_its_links_changed_runs_in_the_background(source, session):
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection
    from backend.services.collections import reindex_collection
    from task_manager.scheduler.db.TaskOperation import TaskOperation

    collection = _collection(session)
    run_write_transaction(lambda s: reindex_collection(s, s.get(Collection, collection.id)))

    # VODLoft started it, not the user, so finishing it shows no toast.
    session.expire_all()
    assert [(operation.kind, operation.source) for operation in session.scalars(select(TaskOperation))] == [
        ("collection.sync", "SYSTEM"),
    ]


def _save(session, *, custom: bool, order=None, off=(), preview=False, loose=None):
    """Save the Seasons dialog with the seasons in this order of names, or as they are, and these lists off."""
    from backend.api.endpoints.collections.seasons.service import preview_seasons, seasons_view, update_seasons
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction

    view = seasons_view(session, "creator")
    session.rollback()
    seasons = sorted(view.seasons, key=lambda x: order.index(x.name)) if order else view.seasons
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": x.id, "name": x.name} for x in seasons], custom_season_order=custom,
        link_seasons="selected", loose_videos=loose or view.loose_videos,
        playlists=[{"id": p.id, "enabled": p.ref not in off, "season_id": p.season_id} for p in view.playlists],
    )
    work = preview_seasons if preview else update_seasons
    return run_write_transaction(lambda s: work(s, "creator", body))


def test_the_seasons_left_after_others_are_deleted_are_numbered_from_one_in_either_order(source, session):
    source.videos = [_video("a", 2023), _video("b", 2024), _video("c", 2025)]
    source.lists = [_list("PLone", "Cabin, Part 1"), _list("PLtwo", "Cabin, Part 2")]
    source.items = {"PLone": ("a",), "PLtwo": ("b",)}
    collection = _collection(session, mode="selected")
    _index(session, collection, source)
    _save(session, custom=True, order=["Cabin, Part 2", "Cabin, Part 1", "Videos"])
    assert [(name, number) for name, number, _ in _seasons(session)] == [("Cabin, Part 2", 1), ("Cabin, Part 1", 2), ("Videos", 3)]

    # Back in VODLoft's order, the only season left is the first.
    preview = _save(session, custom=False, off=("PLone", "PLtwo"), preview=True)
    assert [(x.name, x.season_number) for x in preview.seasons] == [("Videos", 1)]

    # In the user's own order too: the order stays, and the numbers close up.
    _save(session, custom=True, off=("PLone", "PLtwo"))
    assert [(name, number) for name, number, _ in _seasons(session)] == [("Videos", 1)]


def test_seasons_per_year_made_in_the_users_own_order_go_by_year(source, session):
    source.videos = [_video("a", 2023), _video("b", 2024), _video("c", 2025), _video("d", 2021), _video("e", 2022)]
    source.lists = [_list("PLone", "Cabin")]
    source.items = {"PLone": ("b",)}
    collection = _collection(session, mode="selected")
    _index(session, collection, source)
    _save(session, custom=True, order=["Cabin", "Videos"])

    _save(session, custom=True, loose="by_year")

    # The new seasons per year go by year, each where its year puts it around the user's own Cabin.
    assert [(name, number) for name, number, _ in _seasons(session)] == [
        ("2021", 1), ("2022", 2), ("2023", 3), ("Cabin", 4), ("2025", 5),
    ]


def test_the_seasons_list_marks_the_channel_season_while_it_holds_the_whole_channel(source, session):
    from backend.api.endpoints.seasons.service import get_seasons_list

    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session, channel_season="everything")
    _index(session, collection, source)

    assert [(season.name, season.whole_channel) for season in get_seasons_list(session, "creator")
            if season.whole_channel] == [(next(season.name for season in collection.seasons if season.loose), True)]
    collection.channel_season = "unlisted"
    session.commit()
    assert not any(season.whole_channel for season in get_seasons_list(session, "creator"))
