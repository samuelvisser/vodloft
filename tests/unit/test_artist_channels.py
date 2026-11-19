"""Bandcamp and SoundCloud artists as channels: their albums are the sections, and their collections hold music."""
from __future__ import annotations

import pytest

from sources import SectionKind
from sources.ytdlp import artists


@pytest.mark.parametrize(("url", "root", "artist_page"), [
    ("https://tycho.bandcamp.com/music", "https://tycho.bandcamp.com", True),
    ("https://tycho.bandcamp.com/", "https://tycho.bandcamp.com", True),
    ("https://tycho.bandcamp.com/album/epoch", "https://tycho.bandcamp.com", False),
    ("https://bandcamp.com/discover", None, False),
    ("https://soundcloud.com/flume", "https://soundcloud.com/flume", True),
    ("https://soundcloud.com/flume/albums", "https://soundcloud.com/flume", True),
    ("https://soundcloud.com/flume/sets/palaces", "https://soundcloud.com/flume", False),
    ("https://soundcloud.com/discover", None, False),
    ("https://www.youtube.com/@kurzgesagt", None, False),
])
def test_a_link_belongs_to_the_artist_whose_page_it_is_on(url, root, artist_page):
    assert artists.artist_root(url) == root
    assert artists.is_artist_page(url) is artist_page


def _bandcamp(*args, cookies=None):
    url = args[-1]
    if url.endswith("/music"):
        return {"entries": [{"url": "https://tycho.bandcamp.com/album/epoch"}, {"url": "https://tycho.bandcamp.com/album/dive"},
                            {"url": "https://tycho.bandcamp.com/track/remix"}]}
    if url.endswith("/remix"):
        return {"title": "Epoch (Remix)", "track": "Epoch (Remix)", "release_date": "20190101", "thumbnail": "https://img/remix.jpg"}
    album = url.rsplit("/", 1)[-1]
    return {
        "_type": "playlist", "title": album.title(), "playlist_count": 13 if album == "epoch" else 10,
        "entries": [{"artist": "Tycho", "album_artist": "Tycho", "release_date": "20160930" if album == "epoch" else "20111101",
                     "thumbnail": f"https://img/{album}.jpg"}],
    }


def test_a_bandcamp_artist_lists_albums_newest_first_and_tracks_on_their_own_as_singles(monkeypatch):
    monkeypatch.setattr(artists.runner, "run_json", _bandcamp)
    steps = []

    details = artists.artist_details("https://tycho.bandcamp.com", steps.append)

    assert (details.ref, details.url, details.title, details.facts, details.music) == (
        "tycho", "https://tycho.bandcamp.com", "Tycho", ("2 albums",), True,
    )
    assert [(s.title, s.kind, s.kind_label, s.year, s.item_count) for s in details.sections] == [
        ("Epoch (Remix)", SectionKind.ITEM, "Single", "2019", None),
        ("Epoch", SectionKind.LIST, "Album", "2016", 13),
        ("Dive", SectionKind.LIST, "Album", "2011", 10),
    ]
    assert steps[0] == "Listing the albums" and steps[-1] == "Reading the albums: 3 of 3"


def test_a_soundcloud_artist_has_its_albums_and_a_feed_of_all_its_tracks(monkeypatch):
    def soundcloud(*args, cookies=None):
        url = args[-1]
        if url.endswith("/sets"):
            return {"entries": [{"url": "https://soundcloud.com/flume/sets/palaces"}]}
        return {"_type": "playlist", "title": "Palaces", "album_artist": "Flume", "release_date": "20220520", "playlist_count": 13}

    monkeypatch.setattr(artists.runner, "run_json", soundcloud)
    details = artists.artist_details("https://soundcloud.com/flume", lambda step: None)

    assert (details.ref, details.title) == ("flume", "Flume")
    assert [(s.ref, s.kind) for s in details.sections] == [("flume/sets/palaces", SectionKind.LIST), ("tracks", SectionKind.FEED)]
