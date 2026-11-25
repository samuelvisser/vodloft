from sources import Names

from backend.services.new_lists import ListKind, default_new_link_seasons


def _kind(key, one, many, albums=False):
    return ListKind(key, Names(one, many), albums=albums)


ALBUMS = _kind("album", "album", "albums")
PLAYLISTS = _kind("playlist", "playlist", "playlists")
SETS = _kind("set", "set", "sets")


def test_a_channel_adds_the_kinds_its_site_marks_as_albums_and_skips_the_others():
    marked = _kind("set", "set", "sets", albums=True)
    assert default_new_link_seasons([ALBUMS, marked]) == {"album": "ignore", "set": "add"}


def test_where_the_site_marks_none_a_kind_called_albums_is_added_and_the_others_skipped():
    assert default_new_link_seasons([PLAYLISTS, ALBUMS]) == {"playlist": "ignore", "album": "add"}


def test_kinds_of_other_names_or_a_single_kind_are_all_added():
    assert default_new_link_seasons([PLAYLISTS, SETS]) == {"playlist": "add", "set": "add"}
    assert default_new_link_seasons([PLAYLISTS]) == {"playlist": "add"}


def test_the_lists_of_several_sites_are_named_for_all_of_them():
    assert Names.joined([Names("playlist", "playlists"), Names("show", "shows")]) == Names("playlist or show", "playlists and shows")
    assert Names.joined([Names("album", "albums"), Names("playlist", "playlists"), Names("list", "lists")]) == Names(
        "album, playlist or list", "albums, playlists and lists",
    )
    assert Names.joined([Names("playlist", "playlists"), Names("playlist", "playlists")]) == Names("playlist", "playlists")
