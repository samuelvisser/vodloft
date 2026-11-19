"""What a ytdl-sub configuration becomes in VODLoft, as an :class:`ImportPlan`.

Each subscription becomes a yt-dlp Collection. Its presets become a Collection Local Media Profile
with the same folder layout, and its filters a Download Profile for the pair. Subscriptions with the
same presets share one profile, unless their own values name files differently; then each gets its
own variant of it. Every video in a subscription's download archive is adopted at the path ytdl-sub
wrote it to, so files are matched by video id, not by name.

A VODLoft Collection has one link, so a subscription with several links becomes a Collection of the first one and
the rest are reported. A TV Show Collection of a channel and its own playlists becomes a Collection of the channel
whose playlists are seasons, each with its season's number and name, and a video several of them list stays in the
highest one, as in ytdl-sub.

A Bandcamp or SoundCloud discography becomes the artist, a creator, with its albums the seasons of one Music
collection, with a Music Local Media Profile that keeps ytdl-sub's folder per artist and per album. An artist's music
videos are a Music collection of their own, with a profile for Music videos; a ``+`` map's categories, such as
Concerts, are its link seasons. Every music collection names the artist as ytdl-sub does, and an artist's albums and
music videos join one artist: two collections, "<artist> albums" and "<artist> music videos", or one collection with
both profiles when they download the same link.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from ..choices import SPONSORBLOCK_CATEGORIES, sponsorblock, video_quality
from ..contract import (
    CollectionPlan,
    FilePlan,
    ImportLocation,
    ImportPlan,
    ImportWarning,
    PlaylistSeasonPlan,
    ProfilePlan,
    SettingPlan,
)
from ..paths import PathMap, map_path, template_root
from ..uploads import UploadFile
from ..ytdlp_templates import (
    ConversionOptions,
    FieldValue,
    convert_ytdl_sub,
    expand_ytdl_sub,
    render_ytdl_sub,
)
from .archive import ArchiveEntry, archive_names, read_archive
from .presets import (
    DOWNLOAD_HELPERS,
    MUSIC_GENRE_DEFAULT,
    MUSIC_VIDEO_GENRE_DEFAULT,
    MUSIC_VIDEO_VALUES,
    MUSIC_PRESET_VALUES,
    MUSIC_TRACK_VALUES,
    TV_SHOW_CONTENT_RATING_DEFAULT,
    TV_SHOW_GENRE_DEFAULT,
)
from .reader import Subscription, YtdlSubData, override_list, read_ytdl_sub

KEY = "ytdl-sub"
NAME = "ytdl-sub"

_SEASONS = {
    "upload-year": "{upload_year}",
    "upload-year-month": "{upload_year}{upload_month_padded}",
    "release-year": "{release_year}",
    "release-year-month": "{release_year}{release_month_padded}",
}
# Each ordering's episode number, and the Custom Index it holds with how to read it from a file name.
_BY_DATE_EPISODES = {
    "upload-day": ("{upload_day_padded}{upload_date_index_padded}", "day"),
    "upload-month-day": ("{upload_month_padded}{upload_day_padded}{upload_date_index_padded}", "day"),
    "release-day": ("{release_day_padded}{upload_date_index_padded}", "day"),
    "release-month-day": ("{release_month_padded}{release_day_padded}{upload_date_index_padded}", "day"),
    "download-index": ("{download_index_padded6}", "autonumber"),
}
_COLLECTION_EPISODES = {
    "upload-year-month-day": ("{upload_year_truncated}{upload_month_padded}{upload_day_padded}{upload_date_index_padded}", "day"),
    "release-year-month-day": ("{release_year_truncated}{release_month_padded}{release_day_padded}{upload_date_index_padded}", "day"),
    "playlist-index": ("{playlist_index_padded6}", "playlist"),
}
# ytdl-sub's backwards numbers, so the newest episode sorts first.
_REVERSED_EPISODES = {
    "upload-month-day-reversed": ("{upload_day_of_year_reversed_padded}{upload_date_index_reversed_padded}", "day"),
    "release-month-day-reversed": ("{release_day_of_year_reversed_padded}{upload_date_index_reversed_padded}", "day"),
    "upload-year-month-day-reversed": (
        "{upload_year_truncated_reversed}{upload_day_of_year_reversed_padded}{upload_date_index_reversed_padded}", "day",
    ),
    "release-year-month-day-reversed": (
        "{release_year_truncated_reversed}{release_day_of_year_reversed_padded}{upload_date_index_reversed_padded}", "day",
    ),
}
_EPISODE_NUMBER = re.compile(r"\.e(\d+) - ")

_HEIGHTS = ((4320, "format_8k"), (2160, "format_4k"), (1440, "format_1440p"), (1080, "format_1080p"),
            (720, "format_720p"), (480, "format_480p"), (360, "format_360p"))
_AUDIO_FORMATS = {"mp3": "mp3", "opus": "opus", "m4a": "m4a", "aac": "m4a"}
# Lossless, which only a profile for Music tracks keeps.
_MUSIC_AUDIO_FORMATS = {**_AUDIO_FORMATS, "flac": "flac"}
_THROTTLE_OPTIONS = frozenset({
    "sleep_interval", "max_sleep_interval", "sleep_interval_requests", "sleep_interval_subtitles", "ratelimit",
    "throttledratelimit",
})
# ytdl_options ytdl-sub's own presets set, or that the import reads elsewhere.
_HANDLED_OPTIONS = frozenset({"break_on_existing", "merge_output_format", "cookiefile", "max_downloads", "playlistreverse"})
_READ_KEYS = frozenset({
    "preset", "overrides", "output_options", "ytdl_options", "download", "format", "audio_extract", "file_convert",
    "date_range", "subtitles", "chapters", "nfo_tags", "output_directory_nfo_tags", "video_tags", "embed_thumbnail",
    "throttle_protection", "music_tags",
})
_SCRIPT_KEYS = ("filter_include", "filter_exclude", "match_filters")
_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
_RELATIVE = re.compile(r"^(?:today|now)-(\d+)(day|week|month|year)s?$")


@dataclass
class _Layout:
    computed: dict[str, str] = field(default_factory=dict)
    index: str | None = None
    """The Custom Index the episode number holds: day, autonumber or playlist."""
    warnings: list[ImportWarning] = field(default_factory=list)


@dataclass
class _Planned:
    subscription: Subscription
    chain: str
    profile: ProfilePlan
    signature: tuple
    collection: CollectionPlan
    folder: str | None
    """The subscription's output folder, as ytdl-sub names it."""
    index: str | None
    kind: str | None = None


def _kind_and_player(sub: Subscription) -> tuple[str | None, str | None]:
    kind = player = None
    for _name, builtin in sub.builtins():
        kind = builtin.kind or kind
        player = builtin.player or player
    return kind, player


def _layout(sub: Subscription, kind: str | None) -> _Layout:
    overrides = sub.overrides
    layout = _Layout()
    if kind == "tv_show_by_date":
        season = str(overrides.get("tv_show_by_date_season_ordering", "")).lower()
        episode = str(overrides.get("tv_show_by_date_episode_ordering", "")).lower()
        if season in _SEASONS:
            layout.computed.update(season_number=_SEASONS[season], season_number_padded=_SEASONS[season])
        if episode in _BY_DATE_EPISODES:
            layout.computed["episode_number_padded"], layout.index = _BY_DATE_EPISODES[episode]
        elif episode in _REVERSED_EPISODES:
            layout.computed["episode_number_padded"], layout.index = _REVERSED_EPISODES[episode]
        release = "release" in season
    elif kind == "tv_show_collection":
        layout.computed.update(
            season_number="{collection_season_number}", season_number_padded="{collection_season_number_padded}",
        )
        episode = str(overrides.get("tv_show_collection_episode_ordering", "")).lower()
        if episode in _COLLECTION_EPISODES:
            layout.computed["episode_number_padded"], layout.index = _COLLECTION_EPISODES[episode]
        elif episode in _REVERSED_EPISODES:
            layout.computed["episode_number_padded"], layout.index = _REVERSED_EPISODES[episode]
        elif episode.endswith("-reversed"):
            layout.computed["episode_number_padded"] = "{playlist_index_reversed_padded6}"
            layout.warnings.append(ImportWarning(
                "tv_show_collection_episode_ordering",
                f"VODLoft can't number a playlist's videos backwards ({episode}), so new episodes get no episode number",
            ))
        release = "release" in episode
    else:
        return layout
    layout.computed.setdefault("episode_number", layout.computed.get("episode_number_padded", ""))
    layout.computed["episode_date_standardized"] = "{release_date_standardized}" if release else "{upload_date_standardized}"
    return layout


def _season_urls(sub: Subscription, number: int) -> list[str]:
    value = sub.overrides.get(f"s{number:02d}_url")
    urls = override_list(value) if isinstance(value, (list, str)) and override_list(value) is not None else \
        [value] if isinstance(value, str) and value else []
    return [str(url) for url in urls if url and "{" not in str(url)]


@dataclass(frozen=True)
class _Links:
    url: str
    """The Collection's own link."""
    playlists: list[PlaylistSeasonPlan]
    """The Collection's link seasons: every other link of a subscription of a channel."""
    left_out: list[str]
    channel_season: PlaylistSeasonPlan | None = None
    """The TV Show Collection's season of the channel itself, which keeps its videos in none of the playlists."""
    links_only: bool = False
    """The subscription has only playlists and single videos, of no one channel: the Collection holds only them."""


_CHANNEL_TABS = frozenset({"videos", "streams", "shorts", "live", "featured", "playlists"})


def _is_playlist(url: str) -> bool:
    return "list=" in (urlsplit(url).query or "")


def _is_video(url: str) -> bool:
    parts = urlsplit(url)
    return parts.path.startswith(("/watch", "/shorts/")) or (parts.hostname or "").endswith("youtu.be")


def _links(sub: Subscription, kind: str | None) -> _Links | None:
    """The subscription's own link and, for a TV Show Collection of a channel, its playlists that are seasons, the one
    that keeps a video several of them list first: ytdl-sub keeps it in the highest season."""
    if kind != "tv_show_collection":
        if not sub.urls:
            return None
        channel = next((url for url in sub.urls if not _is_playlist(url) and not _is_video(url)), None)
        if kind == "music" or channel is None or len(sub.urls) == 1:
            return _Links(sub.urls[0], [], list(sub.urls[1:]))
        # The channel is the Collection; each other link is a link season, so none of its videos are left out.
        return _Links(channel, [PlaylistSeasonPlan(url, _link_name(url)) for url in sub.urls if url != channel], [])
    seasons = []
    for number in (*range(40, 0, -1), 0):
        name = _render(sub, sub.overrides[f"s{number:02d}_name"]) if sub.overrides.get(f"s{number:02d}_name") else None
        for url in _season_urls(sub, number):
            seasons.append((number, name or ("Specials" if number == 0 else f"Season {number}"), url))
    if not seasons:
        return None
    by_number = sorted(seasons, key=lambda season: (season[0] == 0, season[0]))
    channel = next((season for season in by_number if not _is_playlist(season[2]) and not _is_video(season[2])), None)
    if channel is None:
        # Only playlists and videos: the Collection holds only what they have, each one a season, without a link of
        # its own.
        playlists = [PlaylistSeasonPlan(url, name, number) for number, name, url in seasons]
        return _Links(by_number[0][2], playlists, [], links_only=True)
    # Every other link, a playlist, another channel or one video, is a link season, which adds its videos the
    # channel does not have, so the Collection keeps everything the subscription had.
    playlists = [PlaylistSeasonPlan(url, name, number) for number, name, url in seasons if url != channel[2]]
    return _Links(channel[2], playlists, [], PlaylistSeasonPlan(channel[2], channel[1], channel[0]))


def _map_links(sub: Subscription) -> _Links | None:
    """A ``+`` map's links, each a link season named after its category, such as Concerts. A link of a channel is the
    collection's own; without one, the collection holds only what the links have."""
    numbered = [(number, category, url) for number, (category, links) in enumerate(sub.categories, start=1)
                for url in links if "{" not in url]
    if not numbered:
        return None
    channel = next((item for item in numbered if not _is_playlist(item[2]) and not _is_video(item[2])), None)
    if channel is None:
        return _Links(numbered[0][2], [PlaylistSeasonPlan(url, category, number) for number, category, url in numbered],
                      [], links_only=True)
    others = [PlaylistSeasonPlan(url, category, number) for number, category, url in numbered if url != channel[2]]
    return _Links(channel[2], others, [], PlaylistSeasonPlan(channel[2], channel[1], channel[0]))


def _link_name(url: str) -> str | None:
    """A name for the season of another channel, such as @handle, until the user gives it one; a playlist is named
    as its Site lists it."""
    if _is_playlist(url) or _is_video(url):
        return None
    return next((part for part in reversed(urlsplit(url).path.split("/")) if part and part not in _CHANNEL_TABS), None)


def _render(sub: Subscription, value: object) -> str | None:
    return render_ytdl_sub(str(value), sub.overrides, {"subscription_name": sub.name})


def _days(value: str) -> tuple[int | None, bool]:
    """A date_range's relative date, such as today-2months, in days, and whether that is exact."""
    match = _RELATIVE.match(value.strip().lower())
    if not match:
        return None, False
    unit = match.group(2)
    return int(match.group(1)) * _DAYS[unit], unit in ("day", "week")


def _absolute(value: str) -> date | None:
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8])) if re.fullmatch(r"\d{8}", value) else None
    except ValueError:
        return None


def _best_audio(sub: Subscription) -> str:
    """The format ytdl-sub's ``best`` keeps the site's audio in, without converting it: MP3 on Bandcamp, and Opus
    elsewhere, such as the WebM audio its music presets take from YouTube."""
    return "mp3" if sub.urls and all((urlsplit(url).hostname or "").endswith(".bandcamp.com") for url in sub.urls) else "opus"


def _format_choice(sub: Subscription, warnings: list[ImportWarning]) -> tuple[dict[str, object], bool]:
    """Local Media Profile quality choices for the subscription's format, and whether it is audio only."""
    config = sub.config
    audio = config.get("audio_extract")
    if isinstance(audio, dict):
        codec = str(audio.get("codec", "best")).lower()
        formats = _MUSIC_AUDIO_FORMATS if _kind_and_player(sub)[0] == "music" else _AUDIO_FORMATS
        if codec == "best":
            audio_format = _best_audio(sub)
        else:
            audio_format = formats.get(codec, "m4a")
            if codec not in formats:
                names = "M4A, MP3, Opus or FLAC" if "flac" in formats else "M4A, MP3 or Opus"
                warnings.append(ImportWarning("audio_extract", f"VODLoft saves audio as {names}, not {codec}; it saves M4A", "close"))
        if audio.get("quality") not in (None, 0, "0"):
            warnings.append(ImportWarning("audio_extract", f"VODLoft keeps the best audio the site offers, not {audio['quality']}k", "close"))
        return {"preferred_format": "format_audio_only", "audio_format": audio_format,
                "subtitle_mode": "no_subtitles"}, True
    format_ = str(config.get("format") or "")
    heights = [int(height) for height in re.findall(r"height\s*<=?\s*(\d+)", format_)]
    height = max(heights) if heights else None
    preferred = next((name for limit, name in _HEIGHTS if height is None or limit <= height), "format_360p")
    if height is not None and height not in {limit for limit, _name in _HEIGHTS}:
        warnings.append(ImportWarning("format", f"VODLoft has no {height}p; it downloads up to {preferred.removeprefix('format_')}", "close"))
    convert = (config.get("file_convert") or {}).get("convert_to") if isinstance(config.get("file_convert"), dict) else None
    merge = (config.get("ytdl_options") or {}).get("merge_output_format")
    container = next((value for value in (convert, merge) if value in ("mp4", "mkv")), None)
    if container is None:
        if convert or merge:
            warnings.append(ImportWarning("file_convert", f"VODLoft downloads MP4 or MKV, not {convert or merge}; new downloads are MKV", "close"))
        container = "mkv"
    return {"preferred_format": preferred, **video_quality(container, height is None or height > 1080)}, False


def _subtitle_choices(sub: Subscription) -> tuple[dict[str, object], str]:
    """Local Media Profile subtitle choices, and the Download Profile's auto-generated subtitles."""
    subtitles = sub.config.get("subtitles")
    if not isinstance(subtitles, dict):
        return {"subtitle_mode": "no_subtitles"}, "never"
    embed, sidecar = bool(subtitles.get("embed_subtitles")), bool(subtitles.get("subtitles_name"))
    mode = "embed_and_sidecar" if embed and sidecar else "embed" if embed else "sidecar"
    languages = subtitles.get("languages") or ["en"]
    languages = [languages] if isinstance(languages, str) else [str(language) for language in languages]
    auto = "fallback" if subtitles.get("allow_auto_generated_subtitles") else "never"
    return {"subtitle_mode": mode, "subtitle_languages": languages, "subtitle_language_mode": "listed"}, auto


def _profile_settings(sub: Subscription, player: str | None, warnings: list[ImportWarning]) -> tuple[dict[str, object], bool, str]:
    config = sub.config
    settings, audio = _format_choice(sub, warnings)
    subtitles, auto = _subtitle_choices(sub)
    if not audio:
        settings.update(subtitles)
    nfo = player in ("kodi", "jellyfin", "emby") or "nfo_tags" in config
    embed = player is not None or "video_tags" in config
    settings["metadata_mode"] = "embed_and_nfo" if nfo and embed else "nfo" if nfo else "embed" if embed else "no_metadata"
    settings["show_nfo"] = player in ("kodi", "jellyfin", "emby") or "output_directory_nfo_tags" in config
    nfo_tags = config.get("nfo_tags") if isinstance(config.get("nfo_tags"), dict) else {}
    settings["kodi_safe_nfo"] = player == "kodi" or bool(nfo_tags.get("kodi_safe"))
    thumbnail = bool((config.get("output_options") or {}).get("thumbnail_name"))
    embedded = bool(config.get("embed_thumbnail"))
    settings["thumbnail_mode"] = ("embed_and_sidecar" if thumbnail and embedded else "embed" if embedded
                                  else "sidecar" if thumbnail else "no_thumbnail")
    # ytdl-sub's base preset saves the info file; a preset can turn it off with an empty name.
    settings["save_info_json"] = bool((config.get("output_options") or {}).get("info_json_name"))
    settings["collection_scope"] = "both"
    overrides = sub.overrides
    settings["download_collection_assets"] = bool(overrides.get("tv_show_poster_file_name") or overrides.get("tv_show_fanart_file_name"))
    return settings, audio, auto


def _option_warnings(sub: Subscription) -> list[ImportWarning]:
    warnings: list[ImportWarning] = []
    options = sub.config.get("ytdl_options") or {}
    throttle = sorted(key for key in options if key in _THROTTLE_OPTIONS)
    if throttle or "throttle_protection" in _own_keys(sub) or any(
        key in sub.overrides and sub.overrides[key] is not True for key in ("enable_throttle_protection", "enable_resolution_assert")
    ) or override_list(sub.overrides.get("resolution_assert_ignore_titles")):
        warnings.append(ImportWarning(
            "throttle_protection", "VODLoft paces its own requests to YouTube, so ytdl-sub's throttle settings "
            f"{'(' + ', '.join(throttle) + ') ' if throttle else ''}are not imported. To start fewer downloads, "
            "set Automatic downloads per day for the Site in Settings", "close",
        ))
    if "max_downloads" in options:
        warnings.append(ImportWarning(
            "Chunk Downloads", "VODLoft downloads in its own queue, a few at a time, so it needs no chunks. "
            "Automatic downloads per day in Settings limits how many a Site starts in a day", "close",
        ))
    for key in sorted(options):
        if key in _HANDLED_OPTIONS or key in _THROTTLE_OPTIONS:
            continue
        warnings.append(ImportWarning(
            f"ytdl_options {key}", "VODLoft has no setting for this yt-dlp option; add it to the Collection's own "
            "yt-dlp options if you need it",
        ))
    for key in _SCRIPT_KEYS:
        if sub.config.get(key):
            warnings.append(ImportWarning(key, "ytdl-sub's script filters are a language of their own; use the "
                                               "Download Profile's Which episodes instead"))
    for key in sorted(set(sub.config) - _READ_KEYS - set(_SCRIPT_KEYS)):
        warnings.append(ImportWarning(key, "VODLoft has no setting like this ytdl-sub plugin"))
    return warnings


def _own_keys(sub: Subscription) -> set[str]:
    """The keys a subscription or a custom preset set, not ytdl-sub's own presets."""
    builtins = {name for name, _builtin in sub.builtins()}
    return set(sub.config) if any(name not in builtins for name in sub.applied) else set()


def _keywords(sub: Subscription, field_: str, warnings: list[ImportWarning]) -> list[dict[str, object]]:
    rules = []
    for action, which in (("only", "include"), ("skip", "exclude")):
        words = override_list(sub.overrides.get(f"{field_}_{which}_keywords")) or []
        if not words:
            continue
        every = str(sub.overrides.get(f"{field_}_{which}_eval", "ANY")).upper() == "ALL"
        escaped = [re.escape(word.lower()) for word in words]
        pattern = "".join(f"(?=.*{word})" for word in escaped) if every else "|".join(escaped)
        rules.append({"action": action, "field": field_, "pattern": pattern, "ignore_case": True})
    return rules


def _duration_rules(sub: Subscription) -> list[dict[str, object]]:
    rules = []
    try:
        shortest = float(sub.overrides.get("filter_duration_min_s", 0) or 0)
        longest = float(sub.overrides.get("filter_duration_max_s", 4294967296) or 4294967296)
    except (TypeError, ValueError):
        return rules
    if shortest > 0:
        rules.append({"action": "skip", "field": "duration", "duration_operator": "shorter", "duration_seconds": int(shortest)})
    if longest < 4294967296:
        rules.append({"action": "skip", "field": "duration", "duration_operator": "longer", "duration_seconds": int(longest)})
    return rules


def _episode_types(url: str) -> list[str]:
    tab = url.rstrip("/").rsplit("/", 1)[-1].lower()
    return {"shorts": ["short"], "streams": ["livestream"], "videos": ["ep"]}.get(tab, ["ep", "short", "livestream"])


def _chapters(sub: Subscription, warnings: list[ImportWarning]) -> dict[str, object]:
    """The chapters plugin: SponsorBlock, keeping the video's own chapters and cutting out chapters by title."""
    chapters = sub.config.get("chapters") if isinstance(sub.config.get("chapters"), dict) else None
    if chapters is None:
        return {**sponsorblock({}), "keep_chapters": False, "cut_chapters": []}
    removed_titles = chapters.get("remove_chapters_regex")
    cut = [_render(sub, str(pattern)) for pattern in removed_titles] if isinstance(removed_titles, list) else []
    if chapters.get("allow_chapters_from_comments"):
        warnings.append(ImportWarning(
            "allow_chapters_from_comments", "VODLoft only keeps the chapters a video has itself, not ones from its comments",
        ))
    patterns = []
    for pattern in filter(None, cut):
        try:
            re.compile(pattern)
        except re.error:
            warnings.append(ImportWarning("remove_chapters_regex", f"VODLoft can't read the regular expression {pattern}"))
        else:
            patterns.append(pattern)
    return {
        **_sponsorblock(sub, chapters),
        "keep_chapters": bool(chapters.get("embed_chapters", True)),
        "cut_chapters": patterns,
    }


def _sponsorblock(sub: Subscription, chapters: dict) -> dict[str, object]:
    def categories(value: object) -> set[str]:
        if value == "all":
            return set(SPONSORBLOCK_CATEGORIES)
        return {str(item) for item in value} if isinstance(value, list) else set()

    marked, removed = categories(chapters.get("sponsorblock_categories")), categories(chapters.get("remove_sponsorblock_categories"))
    return sponsorblock({**{category: "chapter" for category in marked}, **{category: "cut" for category in removed}})


def _download_profile(sub: Subscription, url: str, auto_subtitles: str, warnings: list[ImportWarning]) -> dict[str, object]:
    limits: dict[str, object] = {"download_days_in_past": 0, "download_episode_count": 0, "download_starting_from": None,
                                 "delete_older_episodes": False, "retention_from": "published"}
    date_range = sub.config.get("date_range") if isinstance(sub.config.get("date_range"), dict) else {}
    after = _render(sub, date_range["after"]) if date_range.get("after") else None
    if after:
        days, exact = _days(after)
        starting = _absolute(after)
        if days:
            limits["download_days_in_past"] = days
            if not exact:
                warnings.append(ImportWarning("date_range", f"{after} becomes the last {days} days", "close"))
        elif starting:
            limits["download_starting_from"] = starting.isoformat()
        else:
            warnings.append(ImportWarning("date_range", f"VODLoft can't read the date {after}"))
    before = _render(sub, date_range["before"]) if date_range.get("before") else None
    if before:
        until = _absolute(before)
        if until is None:
            warnings.append(ImportWarning("date_range", f"VODLoft only stops at a fixed date, not at {before}"))
        elif limits["download_days_in_past"]:
            warnings.append(ImportWarning(
                "date_range", f"VODLoft limits by days or by dates, not both; the last {limits['download_days_in_past']} "
                              f"days win over {before}", "close",
            ))
        else:
            limits["download_until"] = until.isoformat()
    output = sub.config.get("output_options") or {}
    if output.get("keep_files_after"):
        limits["delete_older_episodes"] = True
    keep = _render(sub, output["keep_max_files"]) if output.get("keep_max_files") is not None else None
    if keep and keep.isdigit() and int(keep) > 0:
        if limits["download_days_in_past"]:
            warnings.append(ImportWarning("keep_max_files", f"VODLoft limits by age or by number, not both; the "
                                                            f"{limits['download_days_in_past']} days win over {keep} files", "close"))
        else:
            limits.update(download_episode_count=int(keep), delete_older_episodes=True)
    if output.get("keep_files_before"):
        warnings.append(ImportWarning("keep_files_before", "VODLoft only deletes older episodes, not newer ones"))
    rules = [*_keywords(sub, "title", warnings), *_keywords(sub, "description", warnings), *_duration_rules(sub)]
    return {
        "enable_profile": True,
        "ep_id_type_list": _episode_types(url),
        "download_with_countdown": False, "redownload_final": False,
        "seasons": [], "include_upcoming_seasons": True,
        "rules": rules,
        "auto_subtitles": auto_subtitles,
        **_chapters(sub, warnings),
        **limits,
    }


def _metadata_value(sub: Subscription, name: str, default: str) -> str | None:
    """The show's genre or rating as ytdl-sub writes it into tvshow.nfo; None for ytdl-sub's own default."""
    value = _render(sub, sub.overrides.get(name, "")) if name in sub.overrides else None
    return value if value and value != default else None


def _collection_type(url: str) -> str:
    return "playlist" if "list=" in url or "/playlist" in url else "channel"


def _music_overrides(sub: Subscription) -> dict[str, str]:
    """ytdl-sub's track values that its own music presets set, as the values a Music profile keeps."""
    return {name: value for name, value in MUSIC_TRACK_VALUES.items()
            if str(sub.overrides.get(name, "")) in MUSIC_PRESET_VALUES[name]}


def _template(
    sub: Subscription, layout: _Layout, folder: str, path_map: PathMap, collection_type: str, music: bool = False,
    music_videos: bool = False,
):
    """The converted Local Media Profile template, and a warning when it starts outside ytdl-sub's folder."""
    output = sub.config.get("output_options") or {}
    directory, file_name = output.get("output_directory"), output.get("file_name")
    original = f"{directory}/{file_name}"
    # The Collection is named after the show, so the template reads the show's name as the Collection's title.
    overrides = {
        **sub.overrides, "tv_show_name": "{subscription_name}", **(_music_overrides(sub) if music else {}),
        **(_music_video_overrides(sub) if music_videos else {}),
    }
    expansion = expand_ytdl_sub(original, overrides, layout.computed)
    prefix = folder.rstrip("/").replace("%", "%%") + "/" if folder != "/" else "/"
    template = expansion.template
    warning = None
    if template.startswith(prefix):
        template = "/" + template[len(prefix):]
    elif folder != "/":
        warning = f"The files are not inside {folder}"
    relative, root, problem = template_root(template, path_map, folder)
    report = convert_ytdl_sub(
        replace(expansion, template=relative), original,
        ConversionOptions(na_placeholder="", root=root, collection_type=collection_type,
                          for_playlists=collection_type == "playlist"),
    )
    return report, problem or warning


_METADATA_TEMPLATES = (("episode_title", "episode_title_template"), ("episode_plot", "episode_description_template"))


def _metadata_templates(sub: Subscription, layout: _Layout, warnings: list[ImportWarning]) -> dict[str, object]:
    """ytdl-sub's own episode title and plot for the NFO and the file's tags, as the profile's templates."""
    templates: dict[str, object] = {}
    for override, setting in _METADATA_TEMPLATES:
        if override not in sub.overrides:
            continue
        original = str(sub.overrides[override])
        # The path converter does the work: the text sits between its root and the extension.
        expansion = expand_ytdl_sub(f"{original}.{{ext}}", sub.overrides, layout.computed)
        report = convert_ytdl_sub(expansion, original, ConversionOptions(
            na_placeholder="", root="/", extra_fields={"description": FieldValue("description", always=True)},
        ))
        converted = report.output_template
        if converted is None or report.support == "unsupported":
            warnings.append(ImportWarning(override, f"VODLoft can't convert {original}, so it keeps the site's text"))
            continue
        templates[setting] = converted.removeprefix("/").removesuffix(".ext")
    return templates


_MUSIC_SETTINGS: dict[str, object] = {
    "collection_scope": "music_tracks", "metadata_mode": "embed", "thumbnail_mode": "embed",
    "show_nfo": False, "kodi_safe_nfo": False, "download_collection_assets": False,
}
"""A Local Media Profile for Music tracks: tags and a square cover in each file, as ytdl-sub's music presets write
them."""


_MUSIC_VIDEO_SETTINGS: dict[str, object] = {
    "collection_scope": "music_videos", "episode_nfo": "music_video", "show_nfo": False, "download_collection_assets": False,
}
"""A Collection profile of music videos: a musicvideo NFO by the creator as artist, and no show or season files."""


def _music_video_overrides(sub: Subscription) -> dict[str, str]:
    """The artist as ytdl-sub's music video presets set it, as the artist VODLoft's template reads."""
    return {name: value for name, value in MUSIC_VIDEO_VALUES.items()
            if str(sub.overrides.get(name, "")) == "{subscription_name}"}


def _artist(sub: Subscription, kind: str | None) -> str | None:
    """The artist ytdl-sub names a music subscription's files and tags after: its subscription, unless the
    configuration names them otherwise."""
    key = {"music": "track_artist", "music_video": "music_video_artist"}.get(kind or "")
    if key is None:
        return None
    value = _render(sub, sub.overrides.get(key, "{subscription_name}"))
    return value if value and "{" not in value else sub.name


def _music_refusal(sub: Subscription) -> str | None:
    """Why a music subscription is not imported, or None for an artist VODLoft adds as a creator, or for full albums,
    which VODLoft splits into tracks by their chapters."""
    applied = set(sub.applied)
    if "YouTube Full Albums" in applied:
        return None
    if "YouTube Releases" in applied:
        return "yt-dlp can't list YouTube's Releases tab yet, so VODLoft can't follow it"
    if not {"Bandcamp", "SoundCloud Discography"} & applied:
        return "VODLoft adds music from an artist's Bandcamp or SoundCloud page; save a single track with Quick download"
    if not sub.urls or not all(_artist_page(url) for url in sub.urls):
        return "its link is not an artist's Bandcamp or SoundCloud page"
    return None


def _artist_root(url: str) -> tuple[str, str]:
    """The artist a Bandcamp or SoundCloud link is of: its Bandcamp host, or its first SoundCloud path part."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.endswith(".bandcamp.com"):
        return host, ""
    return "soundcloud.com", parts.path.strip("/").split("/", 1)[0].lower()


def _same_artist(artist: str, url: str) -> bool:
    return _artist_page(url) and _artist_root(artist) == _artist_root(url)


def _artist_page(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host.endswith(".bandcamp.com") or host in {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"}


def _plan_subscription(sub: Subscription, folder: str, path_map: PathMap) -> tuple[_Planned | None, list[ImportWarning]]:
    """The subscription's profile and Collection, or None with why it is not imported."""
    kind, player = _kind_and_player(sub)
    if sub.unknown:
        return None, [ImportWarning(sub.name, f"Not imported: VODLoft doesn't know the preset {', '.join(sub.unknown)}")]
    if sub.map and kind != "music_video":
        return None, [ImportWarning(sub.name, "Not imported: VODLoft reads ytdl-sub's + maps for music videos only")]
    if kind == "music":
        refused = _music_refusal(sub)
        if refused:
            return None, [ImportWarning(sub.name, f"Not imported: {refused}")]
    links = _map_links(sub) if sub.map else _links(sub, kind)
    if links is None:
        return None, [ImportWarning(sub.name, "Not imported: it has no link VODLoft can read")]
    output = sub.config.get("output_options") or {}
    if not output.get("output_directory") or not output.get("file_name"):
        return None, [ImportWarning(sub.name, "Not imported: it has no output folder or file name")]

    layout = _layout(sub, kind)
    warnings = list(layout.warnings)
    if kind == "tv_show_by_date" and "episode_number_padded" not in layout.computed:
        warnings.append(ImportWarning("ordering", "ytdl-sub needs a season and episode ordering for this preset"))
    profile_warnings: list[ImportWarning] = []
    settings, audio, auto_subtitles = _profile_settings(sub, player, profile_warnings)
    music = kind == "music"
    music_videos = kind == "music_video"
    full_albums = music and "YouTube Full Albums" in set(sub.applied)
    if music:
        # Every album of the artist is a season of the artist's collection, so only another artist's links are left out.
        others = [url for url in links.left_out if not _same_artist(links.url, url)]
        if others:
            warnings.append(ImportWarning(
                "links", f"VODLoft adds the artist at {links.url}; left out: {', '.join(others)}", "close",
            ))
        settings.update(_MUSIC_SETTINGS)
    elif music_videos:
        settings.update(_MUSIC_VIDEO_SETTINGS)
        if links.left_out:
            warnings.append(ImportWarning(
                "links", f"VODLoft adds the music videos at {links.url}; add the others to the artist as "
                f"collections of their own: {', '.join(links.left_out)}", "close",
            ))
    elif links.left_out:
        warnings.append(ImportWarning(
            "links", f"A VODLoft collection has one link, {links.url}; left out: {', '.join(links.left_out)}", "close",
        ))
    primary = links.url
    collection_type = _collection_type(primary)
    settings.update(_metadata_templates(sub, layout, profile_warnings))
    report, problem = _template(sub, layout, folder, path_map, collection_type, music, music_videos)
    if problem:
        profile_warnings.append(ImportWarning("output template", problem, "close"))
    if report.output_template is None:
        profile_warnings.append(ImportWarning("output template", "; ".join(report.errors) or "The template could not be converted"))
    chain = " | ".join(name for name in sub.presets if name not in DOWNLOAD_HELPERS) or NAME
    profile = ProfilePlan(
        external_id=f"preset:{chain}", name=chain, output_template=report.output_template,
        custom_indexes=report.custom_indexes, settings=settings, warnings=tuple(profile_warnings),
        original_template=report.original, report=tuple(report.lines()[1:]), support=report.support,
    )
    warnings += _option_warnings(sub)
    directory = _render(sub, output["output_directory"])
    title = _render(sub, sub.overrides.get("tv_show_name", "{subscription_name}")) or sub.name
    custom: dict[str, object] = {"type": "music" if music or music_videos else "podcast" if audio else "series", "episode_identifier": "date_based"}
    if full_albums:
        # Each video is an album, and each of its chapters a track.
        custom["split_chapters"] = True
    metadata = ((("genre", "track_genre", MUSIC_GENRE_DEFAULT),) if music else
                (("genre", "music_video_genre", MUSIC_VIDEO_GENRE_DEFAULT),) if music_videos else
                (("genre", "tv_show_genre", TV_SHOW_GENRE_DEFAULT),
                 ("content_rating", "tv_show_content_rating", TV_SHOW_CONTENT_RATING_DEFAULT)))
    for name, key, default in metadata:
        value = _metadata_value(sub, key, default)
        if value:
            custom[name] = value
    assets: list[tuple[str, str]] = []
    if directory and not music and not music_videos:
        names = [(kind_, _render(sub, sub.overrides[name]) if sub.overrides.get(name) else None)
                 for kind_, name in (("poster", "tv_show_poster_file_name"), ("fanart", "tv_show_fanart_file_name"))]
        if settings["show_nfo"]:
            names.append(("nfo", "tvshow.nfo"))
        assets = [(kind_, mapped) for kind_, name in names
                  if name and (mapped := map_path(posixpath.join(directory, name), path_map))]
    collection = CollectionPlan(
        external_id=f"subscription:{sub.name}",
        url=primary,
        title=title,
        profile_external_id=profile.external_id,
        settings=custom,
        download_profile=_download_profile(sub, primary, auto_subtitles, warnings),
        warnings=tuple(warnings),
        assets=tuple(assets),
        link_seasons=tuple(links.playlists),
        loose_season=links.channel_season if links.playlists else None,
        links_only=links.links_only,
        # An artist's page is the artist; other music, such as music videos, joins the creator behind its link.
        creator=music and not full_albums,
        artist=_artist(sub, kind),
    )
    signature = (report.output_template, report.original, repr(sorted(settings.items())))
    return _Planned(sub, chain, profile, signature, collection, directory, layout.index, kind), []


def _folder(subscriptions: tuple[Subscription, ...]) -> str:
    """ytdl-sub's download folder: the folder all output folders are in, such as /tv_shows."""
    parents = []
    for sub in subscriptions:
        directory = (sub.config.get("output_options") or {}).get("output_directory")
        rendered = _render(sub, directory) if directory else None
        if rendered and rendered.startswith("/"):
            # A TV show's folder is in the download folder; the music presets write into it, a folder per artist.
            music = _kind_and_player(sub)[0] in ("music", "music_video")
            parents.append(rendered.rstrip("/") or "/" if music else posixpath.dirname(rendered.rstrip("/")) or "/")
    return posixpath.commonpath(parents) if parents else "/downloads"


def _index_value(entry: ArchiveEntry, index: str | None, media: str) -> dict[str, int]:
    if index is None:
        return {}
    if index == "playlist" and entry.playlist_index:
        return {"playlist": entry.playlist_index}
    match = _EPISODE_NUMBER.search(PurePosixPath(media).name)
    if not match:
        return {}
    digits = match.group(1)
    value = int(digits[-2:]) if index == "day" else int(digits)
    return {index: value} if value > 0 else {}


def _title(media: str) -> str | None:
    """The video's title as a TV show preset wrote it after the episode number; the archive keeps no titles."""
    name = PurePosixPath(media).stem
    match = _EPISODE_NUMBER.search(name)
    return (name[match.end():] or None) if match else None


def _files(planned: _Planned, location: ImportLocation) -> tuple[list[FilePlan], int]:
    """The subscription's downloaded files from its archive, and how many it lists outside the mapped folder."""
    if planned.folder is None or location.download_file is None:
        return [], 0
    entries: list[ArchiveEntry] = []
    for name in archive_names(planned.subscription.name):
        mapped = map_path(posixpath.join(planned.folder, name), location.path_map)
        path = location.download_file(mapped) if mapped else None
        if path is not None:
            entries = read_archive(path)
            break
    split = bool(planned.collection.settings.get("split_chapters"))
    files, outside = [], 0
    for entry in entries:
        # A full album wrote a file per track, numbered in its name, so their names sort in the album's order.
        media_files = sorted(entry.media_files) if split else entry.media_files[:1]
        for part, media in enumerate(media_files, start=1):
            mapped = map_path(posixpath.join(planned.folder, media), location.path_map)
            if mapped is None:
                outside += 1
                continue
            index = _index_value(entry, planned.index, media)
            files.append(FilePlan(planned.collection.external_id, entry.uid, mapped, "file", index,
                                  title=_title(media), published=entry.upload_date, part=part if split else None))
    return files, outside


def _variants(planned: list[_Planned]) -> list[ProfilePlan]:
    """One profile per preset chain; a subscription whose own values name files differently gets a variant."""
    by_chain: dict[str, _Planned] = {}
    profiles: dict[str, ProfilePlan] = {}
    for item in planned:
        first = by_chain.setdefault(item.chain, item)
        if first is item or first.signature == item.signature:
            item.profile = first.profile
            profiles.setdefault(first.profile.external_id, first.profile)
            continue
        variant = replace(
            item.profile, external_id=f"preset:{item.chain}:subscription:{item.subscription.name}",
            name=f"{item.chain} ({item.subscription.name})", base_name=item.chain,
        )
        item.profile = variant
        profiles[variant.external_id] = variant
    for item in planned:
        item.collection = replace(item.collection, profile_external_id=item.profile.external_id)
    return list(profiles.values())


def _unique_ids(planned: list[_Planned]) -> list[_Planned]:
    """Each subscription's Collection known by its name; another subscription of the same name, such as an artist's
    music videos beside their albums, by its presets too."""
    seen: set[str] = set()
    for item in planned:
        external_id = item.collection.external_id
        if external_id in seen:
            external_id = f"{external_id}:{item.chain}"
            item.collection = replace(item.collection, external_id=external_id)
        seen.add(external_id)
    return planned


def _same_link(first: str, second: str) -> bool:
    return first.rstrip("/").lower() == second.rstrip("/").lower()


def _artists(planned: list[_Planned]) -> list[_Planned]:
    """Name an artist's albums and music videos for what they are, and plan the albums first, so the music videos
    join the artist their albums make. Albums and music videos of the same link are one collection, named after the
    artist, which keeps both."""
    by_artist: dict[str, dict[str, list[_Planned]]] = {}
    for item in planned:
        if item.collection.artist and item.kind in ("music", "music_video"):
            by_artist.setdefault(item.collection.artist, {}).setdefault(item.kind, []).append(item)
    for artist, kinds in by_artist.items():
        albums, videos = kinds.get("music", []), kinds.get("music_video", [])
        if not albums or not videos:
            continue
        for item in (*albums, *videos):
            same = any(_same_link(item.collection.url, other.collection.url)
                       for other in (videos if item.kind == "music" else albums))
            title = artist if same else f"{artist} albums" if item.kind == "music" else f"{artist} music videos"
            item.collection = replace(item.collection, title=title)
    # Albums first: a stable sort keeps the rest in ytdl-sub's order.
    return sorted(planned, key=lambda item: item.kind != "music")


def _settings(data: YtdlSubData, folder: Path | None) -> list[SettingPlan]:
    settings = [SettingPlan(
        "downloads.filename_restriction_mode", "windows",
        note="ytdl-sub names files the way yt-dlp does, which is VODLoft's Windows-compatible mode",
    )]
    cookies = folder / "cookies.txt" if folder is not None else None
    uses_cookies = any((sub.config.get("ytdl_options") or {}).get("cookiefile") for sub in data.subscriptions)
    if uses_cookies and cookies is not None and cookies.is_file() and cookies.stat().st_size > 0:
        settings.append(SettingPlan("ytdlp.cookies", str(cookies), secret=True,
                                    note="It holds a sign-in; VODLoft deletes the uploaded copy once it is used"))
    return settings


def plan_import(data: YtdlSubData, location: ImportLocation) -> ImportPlan:
    folder = _folder(data.subscriptions)
    planned: list[_Planned] = []
    warnings = [ImportWarning(
        NAME, "If ytdl-sub keeps downloading these subscriptions into the same folders, you get duplicates. "
        "Take them out of its cron job, or leave the imported Download Profiles off for now.", "close",
    )]
    for sub in data.subscriptions:
        item, skipped = _plan_subscription(sub, folder, location.path_map)
        warnings += skipped
        if item is not None:
            planned.append(item)
    planned = _artists(_unique_ids(planned))
    profiles = _variants(planned)
    files: list[FilePlan] = []
    outside = 0
    for item in planned:
        found, missed = _files(item, location)
        files += found
        outside += missed
    if outside:
        warnings.append(ImportWarning("files", f"{outside} files are outside the folder VODLoft sees and are not adopted"))
    probes = tuple(posixpath.join(item.folder, archive_names(item.subscription.name)[0])
                   for item in planned if item.folder)
    return ImportPlan(
        importer=KEY,
        profiles=tuple(profiles),
        collections=tuple(item.collection for item in planned),
        files=tuple(files),
        settings=tuple(_settings(data, location.folder)),
        warnings=tuple(warnings),
        download_folder=folder,
        probes=probes,
        creators=True,
    )


UPLOAD_FILES = (
    UploadFile("subscriptions.yaml", required=True),
    UploadFile("config.yaml"),
    UploadFile("cookies.txt", secret=True),
)
"""What a ytdl-sub upload takes from its config folder."""


class YtdlSubImporter:
    key = KEY
    name = NAME
    upload_files = UPLOAD_FILES
    database = "subscriptions.yaml"
    extras = None

    def read(self, location: ImportLocation) -> ImportPlan:
        config = location.folder / "config.yaml" if location.folder is not None else None
        return plan_import(read_ytdl_sub(location.database, config), location)
