"""Each collection type's contract, and the words the API serves from them."""
from __future__ import annotations

import json
from pathlib import Path

from backend.api.endpoints.config.service import get_collection_contracts
from backend.db.models import Collection
from backend.services.sites import collection_words, joined_names
from backend.types.collection_contracts import (
    CONTRACTS,
    DEFAULT_WORDS,
    CollectionContract,
    collection_contract,
)
from backend.types.collection_types import CollectionType
from sources import Names

UI_FIXTURE = Path(__file__).parents[2] / "ui" / "tests" / "fixtures" / "collectionContracts.json"


def test_every_type_has_a_contract_that_sets_only_what_differs_from_the_fallback():
    assert set(CONTRACTS) == set(CollectionType)
    for collection_type in (CollectionType.PODCAST, CollectionType.SERIES):
        assert collection_contract(collection_type) == CollectionContract(collection_type)
        assert collection_contract(collection_type).words_for(audio=True) == DEFAULT_WORDS
    music = collection_contract("music")
    assert (music.words.season.one, music.words.episode.one, music.words_for(audio=True).episode.one) == (
        "album", "music video", "track")


def test_a_collection_takes_sound_words_on_a_site_with_sound_only():
    on_bandcamp = Collection(source_key="ytdlp", type="music", sharing_url="https://show.bandcamp.com/music")
    on_youtube = Collection(source_key="ytdlp", type="music", sharing_url="https://www.youtube.com/@show")
    assert collection_words(on_bandcamp).episode.many == "tracks"
    assert collection_words(on_youtube).episode.many == "music videos"
    assert collection_words(on_youtube, audio=True).episode.many == "tracks"


def test_a_word_has_its_article():
    assert (Names("album", "albums").a, Names("track", "tracks").a, Names("hour", "hours", "an").a) == (
        "an album", "a track", "an hour")
    assert joined_names([Names("album", "albums"), Names("playlist", "playlists")]).a == "an album or playlist"


def test_the_ui_tests_use_the_words_the_api_serves():
    # The UI's tests load this copy instead of asking the backend; it has to stay what the API gives.
    served = get_collection_contracts().model_dump(by_alias=True, mode="json")
    assert json.loads(UI_FIXTURE.read_text()) == served
