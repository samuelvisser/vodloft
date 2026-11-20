from sources import Names

from backend.services.new_lists import ListKind, default_new_link_seasons, default_new_sections


def _kind(key, one, many, albums=False):
    return ListKind("site", "Site", key, Names(one, many), seasons=True, albums=albums)


ALBUMS = _kind("album", "album", "albums")
PLAYLISTS = _kind("playlist", "playlist", "playlists")
SETS = _kind("set", "set", "sets")


def test_an_artist_adds_the_kinds_their_site_marks_as_albums_and_skips_the_others():
    marked = _kind("set", "set", "sets", albums=True)
    assert default_new_sections([ALBUMS, marked], music=True) == {"site": {"album": "ignore", "set": "season"}}


def test_where_the_site_marks_none_a_kind_called_albums_is_added_and_the_others_skipped():
    assert default_new_sections([PLAYLISTS, ALBUMS], music=True) == {"site": {"playlist": "ignore", "album": "season"}}
    assert default_new_link_seasons([PLAYLISTS, ALBUMS], music=True) == {"playlist": "ignore", "album": "ask"}


def test_kinds_of_other_names_or_a_single_kind_are_all_added():
    assert default_new_sections([PLAYLISTS, SETS], music=True) == {"site": {"playlist": "season", "set": "season"}}
    assert default_new_sections([PLAYLISTS], music=True) == {"site": {"playlist": "season"}}
    assert default_new_link_seasons([PLAYLISTS, SETS], music=True) == {"playlist": "ask", "set": "ask"}


def test_anyone_but_an_artist_is_asked():
    assert default_new_sections([PLAYLISTS, ALBUMS], music=False) == {"site": {"playlist": "ask", "album": "ask"}}


def test_the_lists_of_several_sites_are_named_for_all_of_them():

    assert Names.joined([Names("playlist", "playlists"), Names("show", "shows")]) == Names("playlist or show", "playlists and shows")
    assert Names.joined([Names("album", "albums"), Names("playlist", "playlists"), Names("list", "lists")]) == Names(
        "album, playlist or list", "albums, playlists and lists",
    )
    assert Names.joined([Names("playlist", "playlists"), Names("playlist", "playlists")]) == Names("playlist", "playlists")


def test_each_site_has_its_settings_of_its_own():
    other = ListKind("other", "Other", "album", Names("album", "albums"), seasons=True)
    assert default_new_sections([ALBUMS, PLAYLISTS, other], music=True) == {
        "site": {"album": "season", "playlist": "ignore"}, "other": {"album": "season"},
    }
