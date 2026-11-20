"""Each collection type's contract, and the words the API serves from them."""
from __future__ import annotations

import json
from pathlib import Path

from backend.api.endpoints.config.service import get_collection_contracts
from backend.db.models import Collection
from backend.services.sites import collection_words
from backend.types.collection_contracts import (
    CONTRACTS,
    DEFAULT_WORDS,
    CollectionContract,
    collection_contract,
)
from backend.types.collection_types import CollectionType
from backend.types.local_media_profile_types import CollectionLocalMediaProfileScope
from sources import Names

UI_FIXTURE = Path(__file__).parents[2] / "ui" / "tests" / "fixtures" / "collectionContracts.json"


def test_every_type_has_a_contract_that_sets_only_what_differs_from_the_fallback():
    assert set(CONTRACTS) == set(CollectionType)
    scope = CollectionLocalMediaProfileScope
    assert collection_contract("series") == CollectionContract(CollectionType.SERIES, profile_scope=scope.SERIES)
    assert collection_contract("podcast") == CollectionContract(
        CollectionType.PODCAST, profile_scope=scope.PODCAST, downloads_by_season=False)
    for collection_type in (CollectionType.PODCAST, CollectionType.SERIES):
        assert collection_contract(collection_type).words_for(audio=True) == DEFAULT_WORDS
    music = collection_contract("music")
    assert (music.words.season.singular, music.words.episode.singular, music.words_for(audio=True).episode.singular) == (
        "album", "music video", "track")


def test_a_collection_takes_sound_words_on_a_site_with_sound_only():
    on_bandcamp = Collection(source_key="ytdlp", type="music", sharing_url="https://show.bandcamp.com/music")
    on_youtube = Collection(source_key="ytdlp", type="music", sharing_url="https://www.youtube.com/@show")
    assert collection_words(on_bandcamp).episode.plural == "tracks"
    assert collection_words(on_youtube).episode.plural == "music videos"
    assert collection_words(on_youtube, audio=True).episode.plural == "tracks"


def test_a_word_has_its_article():
    assert (Names("album", "albums").a, Names("track", "tracks").a, Names("hour", "hours", "an").a) == (
        "an album", "a track", "an hour")
    assert Names.joined([Names("album", "albums"), Names("playlist", "playlists")]).a == "an album or playlist"


def test_the_ui_tests_use_the_words_the_api_serves():
    # The UI's tests load this copy instead of asking the backend; it has to stay what the API gives.
    served = get_collection_contracts().model_dump(by_alias=True, mode="json")
    assert json.loads(UI_FIXTURE.read_text()) == served


def test_only_a_podcast_downloads_its_newest_episodes_instead_of_by_season():
    assert [contract.type for contract in CONTRACTS.values() if not contract.downloads_by_season] == [CollectionType.PODCAST]


def test_a_site_names_its_media_and_every_section_kind():
    from sources import SectionKind
    from sources.ytdlp.sites import site_of

    assert (site_of("youtube").media_names.plural, site_of("bandcamp").media_names.plural) == ("videos", "tracks")
    # YouTube names no type for single items, so they get VODLoft's own word, with its article.
    assert site_of("youtube").section_type(None, SectionKind.ITEM).names.a == "a video"


def test_a_music_collection_calls_its_creator_an_artist_on_every_site():
    from sources import Site

    host = Site("cast", "Cast", creator_names=Names("host", "hosts"))
    assert collection_contract("music").creator_names_on(host) == Names("artist", "artists")
    assert collection_contract("series").creator_names_on(host) == Names("host", "hosts")


def test_a_type_offers_the_profiles_that_keep_it_and_starts_a_new_one_for_it():
    scope = CollectionLocalMediaProfileScope
    assert collection_contract("podcast").profile_scopes == (scope.BOTH, scope.PODCAST)
    assert collection_contract("music").profile_scopes == (scope.MUSIC_TRACKS, scope.MUSIC_VIDEOS)
    assert (collection_contract("music").profile_scope, collection_contract("music").audio_profile_scope) == (
        scope.MUSIC_VIDEOS, scope.MUSIC_TRACKS)
    assert collection_contract("series").audio_profile_scope == scope.SERIES


def test_a_music_collection_keeps_its_albums_in_the_artists_order_and_names_its_media_as_its_episodes():
    from sources import site_of

    music, series = collection_contract("music"), collection_contract("series")
    assert (music.site_order, music.album_lists, series.site_order, series.album_lists) == (True, True, False, False)
    youtube, bandcamp = site_of("youtube"), site_of("bandcamp")
    assert music.media_names_on(youtube) == Names("music video", "music videos")
    assert music.media_names_on(bandcamp) == Names("track", "tracks")
    assert series.media_names_on(youtube) == Names("video", "videos")
    assert (music.loose_season_on(bandcamp), series.loose_season_on(bandcamp), series.loose_season_on(youtube)) == (
        "Singles", "Tracks", "Videos")
