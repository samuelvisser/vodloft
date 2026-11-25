"""The yt-dlp sites' own contracts, and OtherSites for whatever they leave out."""
from dataclasses import replace

import pytest
from sources import SiteSetting, site_for
from sources.ytdlp.site_contracts import CONTRACTS, OtherSites
from sources.ytdlp.sites import site_of


def _without_identity(site):
    return replace(site, key="", name="", initials="", domains=(), accesses=())


def test_a_contract_that_only_names_its_locked_content_takes_everything_else_from_other_sites():
    floatplane = site_of("floatplane", "floatplane.com")

    assert floatplane.name == "Floatplane"
    assert floatplane.access("members").description == "Only subscribers of the creator can watch this."
    # The general name of what Floatplane names no differently.
    assert floatplane.access("premium").label == "Premium only"
    assert _without_identity(floatplane) == _without_identity(site_of("arte", "arte.tv"))


def test_a_site_without_a_contract_is_named_after_its_domain():
    assert site_of("arte", "arte.tv").name == "arte.tv"


def test_a_page_only_the_generic_extractor_handles_gets_what_other_sites_offer():
    site = site_for("https://example.com/clip.mp4", "ytdlp")

    assert site.key == "generic:example.com"
    assert site.downloads == OtherSites.downloads
    assert site.settings.offers(SiteSetting.CHAPTERS)
    assert [access.label for access in site.accesses] == ["Subscribers only", "Premium only"]


def test_youtube_keeps_the_chapters_other_sites_show_beside_sponsorblock():
    shows = site_of("youtube").settings.shows

    assert {SiteSetting.CHAPTERS, SiteSetting.SPONSORBLOCK, SiteSetting.SPONSORBLOCK_SEGMENTS} <= shows


def test_a_sites_contract_is_built_once():
    assert site_for("https://youtu.be/a", "ytdlp") is site_for("https://youtu.be/b", "ytdlp")


def test_a_contract_can_only_set_what_a_site_has():
    with pytest.raises(TypeError, match="creator_lable"):
        type("Misspelled", (OtherSites,), {"key": "misspelled", "creator_lable": "artist"})


def test_every_contract_has_a_key_of_its_own():
    assert all(key == contract.key for key, contract in CONTRACTS.items())
    assert len(CONTRACTS) == len({contract.__name__ for contract in CONTRACTS.values()})


def test_soundcloud_and_bandcamp_name_their_sections_and_seasons():
    soundcloud, bandcamp = site_of("soundcloud"), site_of("bandcamp")

    assert [(t.key, t.names.plural) for t in soundcloud.section_types] == [
        ("tracks", "tracks"), ("album", "albums"), ("playlist", "playlists"), ("single", "singles"),
    ]
    assert [(t.key, t.names.plural) for t in bandcamp.section_types] == [("album", "albums"), ("single", "singles")]
    # What is in none of an artist's albums and playlists is their singles, as on every Site with sound only.
    assert soundcloud.loose_season == bandcamp.loose_season == "Singles"
    from backend.types.collection_contracts import MUSIC

    assert MUSIC.loose_season_on(soundcloud) == MUSIC.loose_season_on(bandcamp) == "Singles"


def test_every_site_implementation_answers_the_section_types_of_its_contract():
    from sources.ytdlp.site_implementations import IMPLEMENTATIONS

    generic = site_of("example").section_types
    for key, implementation in IMPLEMENTATIONS.items():
        site = site_of(key)
        if site.section_types == generic:
            # A Site whose implementation only adds its search keeps the generic types, read the generic way.
            assert not implementation.list_keys, key
            continue
        answered = implementation(site, lambda url: {})
        assert {type_.key for type_ in site.section_types} == (
            {type_.key for type_ in answered.feed_types} | implementation.list_keys
        ), key


def test_lists_are_named_together_in_their_sites_words():
    soundcloud = site_of("soundcloud")
    assert soundcloud.section_list_names.plural == "albums and playlists"


def test_each_feed_gives_its_videos_a_tag_of_its_site_and_youtube_tells_its_feeds_apart():
    from sources import SectionKind

    for key in CONTRACTS:
        site = site_of(key)
        tags = {tag.key for tag in site.episode_tags}
        feeds = [type_ for type_ in site.section_types if type_.kind is SectionKind.FEED]
        assert all(type_.episode_tag in tags for type_ in feeds), key
        assert len({type_.episode_tag for type_ in feeds}) == len(feeds), key
    youtube = {type_.key: type_.episode_tag for type_ in site_of("youtube").section_types if type_.kind is SectionKind.FEED}
    assert youtube == {"videos": "ep", "shorts": "short", "live": "livestream"}


def _implementation(url):
    from sources.ytdlp import sites
    from sources.ytdlp.site_implementations import IMPLEMENTATIONS, OtherSitesImplementation

    site = sites.site_for(url)
    return IMPLEMENTATIONS.get(site.key, OtherSitesImplementation)(site, lambda url: {})


@pytest.mark.parametrize(("url", "root"), [
    ("https://www.twitch.tv/Spamfish", "https://www.twitch.tv/spamfish"),
    ("https://m.twitch.tv/spamfish/videos?filter=archives", "https://www.twitch.tv/spamfish"),
    ("https://www.twitch.tv/spamfish/clip/SomeClip", "https://www.twitch.tv/spamfish"),
    ("https://www.twitch.tv/videos/123", None),
    ("https://www.twitch.tv/directory/category/chess", None),
    ("https://www.tiktok.com/@scout2015", "https://www.tiktok.com/@scout2015"),
    ("https://www.tiktok.com/@scout2015/video/6718335390845095173", "https://www.tiktok.com/@scout2015"),
])
def test_twitch_channels_and_tiktok_accounts_are_creators(url, root):
    implementation = _implementation(url)
    assert implementation.creator_root(url) == root


def test_a_twitch_channels_collection_lists_its_videos_and_clips():
    implementation = _implementation("https://www.twitch.tv/spamfish")
    videos = "https://www.twitch.tv/spamfish/videos?filter=all"
    # The channel's front page shows its stream; a collection of it lists its videos.
    assert implementation.collection_link("https://www.twitch.tv/spamfish") == videos
    assert implementation.collection_link("https://www.twitch.tv/spamfish/videos?filter=archives").endswith("archives")
    assert implementation.is_creator_page(videos)
    assert implementation.listing_urls(videos) == [videos, "https://www.twitch.tv/spamfish/clips?filter=clips&range=all"]
    assert implementation.listing_urls(videos, frozenset({"videos?filter=all"})) == [videos]


def test_a_twitch_clip_gets_the_clip_tag():
    implementation = _implementation("https://www.twitch.tv/spamfish")
    assert implementation.episode_tag({"extractor_key": "TwitchClips"}, "https://clips.twitch.tv/SomeClip") == "clip"
    assert implementation.episode_tag({"extractor_key": "TwitchVod"}, "https://www.twitch.tv/videos/1") == "ep"


def test_instagram_and_x_have_no_creators_and_no_subtitles():
    for key in ("instagram", "twitter"):
        site = site_of(key)
        assert not site.creators and not site.downloads.subtitles and site.cookies_help


def test_the_twitch_api_values_are_tested_before_they_are_stored_and_a_stored_secret_stays(monkeypatch, tmp_path):
    from sources import ApiKeyRejected, cookies, site_api_keys
    from sources.ytdlp import twitch_api
    from sources.ytdlp.source import YtDlpSource

    monkeypatch.setattr(cookies, "cookies_directory", lambda: tmp_path / "cookies")
    tested = []
    monkeypatch.setattr(twitch_api, "test", lambda values: tested.append(dict(values)))
    source, twitch = YtDlpSource(), site_of("twitch")

    with pytest.raises(ApiKeyRejected) as refused:
        source.save_site_api(twitch, {"client_id": "an-id", "client_secret": ""})
    assert refused.value.field == "client_secret" and not tested

    source.save_site_api(twitch, {"client_id": "an-id", "client_secret": "the-secret"})
    source.save_site_api(twitch, {"client_id": "another-id", "client_secret": ""})
    assert tested[-1] == {"client_id": "another-id", "client_secret": "the-secret"}
    status = source.site_api_status(twitch)
    # A secret is only shown by its last characters.
    assert status.hints == {"client_id": "another-id", "client_secret": "…cret"}
    assert source.search_ready(twitch)
    source.remove_site_api(twitch)
    assert site_api_keys.load("twitch") is None and not source.search_ready(twitch)


def test_twitch_search_lists_channels(monkeypatch, tmp_path):
    from sources import cookies, site_api_keys
    from sources.ytdlp import twitch_api
    from sources.ytdlp.source import YtDlpSource

    monkeypatch.setattr(cookies, "cookies_directory", lambda: tmp_path / "cookies")
    site_api_keys.save("twitch", {"client_id": "an-id", "client_secret": "the-secret"})
    monkeypatch.setattr(twitch_api, "_get", lambda values, path, params: {"data": [
        {"broadcaster_login": "spamfish", "display_name": "Spamfish", "is_live": True, "game_name": "Chess", "title": "Live!"},
    ]})
    found = YtDlpSource().search(site_of("twitch"), "spamfish")
    [channel] = found.results
    assert channel.url == "https://www.twitch.tv/spamfish/videos?filter=all"
    assert channel.facts == ("Live now", "Chess")
