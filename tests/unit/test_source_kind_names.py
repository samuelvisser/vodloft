"""A Source can name the common kinds of media in its own words (Beta 0.6.0)."""


def test_sources_list_their_own_words_for_a_collection():
    from backend.api.endpoints.sources.service import list_sources

    names = {source.id: source.kind_names for source in list_sources()}

    assert names["dailywire"] == {"collection": "Show"}
    assert names["npo"] == {"collection": "Series"}
    # yt-dlp names each search result itself, as a Channel or a Playlist.
    assert names["ytdlp"] == {}


def test_kind_names_are_sent_as_camel_case_json():
    from backend.api.endpoints.sources.service import list_sources

    dailywire = next(source for source in list_sources() if source.id == "dailywire")

    assert dailywire.model_dump(by_alias=True)["kindNames"] == {"collection": "Show"}
