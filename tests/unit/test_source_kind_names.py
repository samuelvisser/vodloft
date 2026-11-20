"""A Source can name the common kinds of media in its own words (Beta 0.6.0)."""


def _names(source):
    return {kind: names.singular for kind, names in source.kind_names.items()}


def test_sources_list_their_own_words_for_each_kind_or_vodlofts():
    from backend.api.endpoints.sources.service import list_sources

    names = {source.id: _names(source) for source in list_sources()}

    vodloft = {"collection": "collection", "movie": "movie", "episode": "episode", "video": "video", "creator": "creator"}
    assert names["dailywire"] == {**vodloft, "collection": "show", "creator": "host"}
    assert names["npo"] == {**vodloft, "collection": "series"}
    # yt-dlp names each search result itself, as a Channel or a Playlist.
    assert names["ytdlp"] == vodloft


def test_kind_names_are_sent_as_camel_case_json():
    from backend.api.endpoints.sources.service import list_sources

    dailywire = next(source for source in list_sources() if source.id == "dailywire")

    assert dailywire.model_dump(by_alias=True)["kindNames"]["collection"] == {"singular": "show", "plural": "shows", "a": "a show"}
