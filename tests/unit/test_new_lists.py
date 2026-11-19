from sources import CreatorSectionNames

from backend.services.new_lists import ListKind, default_new_link_seasons, default_new_sections


def _kind(key, one, many, albums=False):
    return ListKind(key, CreatorSectionNames(one, many), seasons=True, albums=albums)


ALBUMS = _kind("album", "an album", "albums")
PLAYLISTS = _kind("playlist", "a playlist", "playlists")
SETS = _kind("set", "a set", "sets")


def test_an_artist_adds_the_kinds_their_site_marks_as_albums_and_skips_the_others():
    marked = _kind("set", "a set", "sets", albums=True)
    assert default_new_sections([ALBUMS, marked], music=True) == {"album": "ignore", "set": "season"}


def test_where_the_site_marks_none_a_kind_called_albums_is_added_and_the_others_skipped():
    assert default_new_sections([PLAYLISTS, ALBUMS], music=True) == {"playlist": "ignore", "album": "season"}
    assert default_new_link_seasons([PLAYLISTS, ALBUMS], music=True) == {"playlist": "ignore", "album": "ask"}


def test_kinds_of_other_names_or_a_single_kind_are_all_added():
    assert default_new_sections([PLAYLISTS, SETS], music=True) == {"playlist": "season", "set": "season"}
    assert default_new_sections([PLAYLISTS], music=True) == {"playlist": "season"}
    assert default_new_link_seasons([PLAYLISTS, SETS], music=True) == {"playlist": "ask", "set": "ask"}


def test_anyone_but_an_artist_is_asked():
    assert default_new_sections([PLAYLISTS, ALBUMS], music=False) == {"playlist": "ask", "album": "ask"}
