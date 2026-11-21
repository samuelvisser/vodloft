"""ytdl-sub's own presets, as far as the import needs to know them.

Each of ytdl-sub's prebuilt presets is described here by what it sets, in ytdl-sub's own keys,
so the reader can merge a subscription's presets the way ytdl-sub does without ytdl-sub itself.
Values that ytdl-sub's presets compute with scripts, such as the season and episode numbers of
an ordering, are left out: the mapping knows each ordering by its name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["tv_show_by_date", "tv_show_collection", "music", "music_video"]
Player = Literal["kodi", "jellyfin", "emby", "plex"]


@dataclass(frozen=True)
class Builtin:
    parents: tuple[str, ...] = ()
    config: dict = field(default_factory=dict)
    """What the preset sets, in ytdl-sub's keys, apart from scripts."""
    kind: Kind | None = None
    player: Player | None = None


_EPISODE_BASE = Builtin(config={
    "output_options": {
        "output_directory": "{tv_show_directory}/{tv_show_name_sanitized}",
        "file_name": "{episode_file_path}.{ext}",
        "thumbnail_name": "{thumbnail_file_name}",
        "info_json_name": "{episode_file_path}.{info_json_ext}",
        "maintain_download_archive": True,
    },
    "ytdl_options": {"break_on_existing": True},
    "chapters": {"embed_chapters": True},
    "overrides": {
        "tv_show_genre_default": "ytdl-sub",
        "tv_show_content_rating_default": "TV-14",
        "subscription_indent_1": "{tv_show_genre_default}",
        "subscription_indent_2": "{tv_show_content_rating_default}",
        "tv_show_name": "{subscription_name}",
        "tv_show_genre": "{subscription_indent_1}",
        "tv_show_content_rating": "{subscription_indent_2}",
        "season_directory_name": "Season {season_number_padded}",
        "episode_file_name": "s{season_number_padded}.e{episode_number_padded} - {file_title}",
        "episode_file_path": "{season_directory_name_sanitized}/{episode_file_name_sanitized}",
        "thumbnail_file_name": "{episode_file_path}-thumb.jpg",
        "file_title": "{title_sanitized}",
        "file_uid": "{uid_sanitized}",
        "tv_show_poster_file_name": "poster.jpg",
        "tv_show_fanart_file_name": "fanart.jpg",
        "enable_throttle_protection": True,
        "enable_resolution_assert": True,
    },
})
_MUSIC_BASE = Builtin(config={
    "output_options": {
        "output_directory": "{music_directory}",
        "file_name": "{track_full_path}",
        "thumbnail_name": "{album_cover_path}",
        "maintain_download_archive": True,
    },
    "ytdl_options": {"break_on_existing": True},
    "format": "ba[ext=webm]/ba",
    "audio_extract": {"codec": "best"},
    "music_tags": {"artist": "{track_artist}", "album": "{track_album}", "track": "{track_number}"},
    "overrides": {
        "track_genre_default": "Unset",
        "subscription_indent_1": "{track_genre_default}",
        "track_title": "{title}",
        "track_album": "{title}",
        "track_artist": "{subscription_name}",
        "track_album_artist": "{track_artist}",
        "track_number": "1",
        "track_number_padded": "01",
        "track_total": "1",
        "track_year": "{upload_year}",
        "track_genre": "{subscription_indent_1}",
        "artist_dir": "{track_artist_sanitized}",
        "album_dir": "[{track_year}] {track_album_sanitized}",
        "track_file_name": "{track_number_padded} - {track_title_sanitized}.{ext}",
        "track_full_path": "{artist_dir}/{album_dir}/{track_file_name}",
        "album_cover_path": "{artist_dir}/{album_dir}/folder.{thumbnail_ext}",
    },
})
"""ytdl-sub's music presets: a folder per artist, a folder per album, a file per track."""
MUSIC_GENRE_DEFAULT = "Unset"
_MUSIC_VIDEO_BASE = Builtin(config={
    "output_options": {
        "output_directory": "{music_video_directory}",
        "file_name": "{music_video_artist_sanitized}/{music_video_title_sanitized}.{ext}",
        "thumbnail_name": "{music_video_artist_sanitized}/{music_video_title_sanitized}.jpg",
        "maintain_download_archive": True,
    },
    "overrides": {
        "music_video_genre_default": "ytdl-sub",
        "subscription_indent_1": "{music_video_genre_default}",
        "music_video_artist": "{subscription_name}",
        "music_video_title": "{title}",
        "music_video_genre": "{subscription_indent_1}",
    },
})
"""ytdl-sub's music video presets: a folder per artist, named after the subscription, with a file per video."""
MUSIC_VIDEO_VALUES = {"music_video_artist": "{music_artist}"}
"""The artist ytdl-sub's music video presets name the folder after: the subscription, which VODLoft's Music Videos
collection gets as its channel's name."""
MUSIC_VIDEO_GENRE_DEFAULT = "ytdl-sub"

MUSIC_TRACK_VALUES = {
    # A track split from a full album's video is an episode of its own, titled after its chapter.
    "track_title": "{title}",
    "track_artist": "{music_artist}",
    "track_album": "{music_album}",
    "track_number": "{music_track_number}",
    "track_number_padded": "{music_track_number_padded}",
    # The year each track came out, which is the album's year for nearly every album.
    "track_year": "{upload_year}",
}
"""What ytdl-sub's music presets read from each album and track, as the values VODLoft's Music profiles keep."""
MUSIC_PRESET_VALUES = {
    "track_title": {"{title}", "{chapter_title}"},
    "track_artist": {"{subscription_name}"},
    "track_album": {"{title}", "{playlist_title}", "{sc_track_album}"},
    "track_number": {"1", "{playlist_index}", "{chapter_index}", "{sc_track_number}"},
    "track_number_padded": {"01", "{playlist_index_padded}", "{chapter_index_padded}", "{sc_track_number_padded}"},
    "track_year": {"{upload_year}", "{playlist_max_upload_year}", "{sc_track_year}"},
}
"""The values ytdl-sub's own music presets give them; a value the configuration changed is kept as written."""

TV_SHOW_GENRE_DEFAULT = "ytdl-sub"
TV_SHOW_CONTENT_RATING_DEFAULT = "TV-14"

_PLEX_FORMAT = "(bv*[ext=mp4][vcodec~='^((he|a)vc|h26[45])']+ba[ext=m4a]) / (bv[ext=mp4]*+ba[ext=m4a]/b)"


def _player(player: Player) -> Builtin:
    if player == "plex":
        return Builtin(("_episode_base",), {
            "format": _PLEX_FORMAT,
            "file_convert": {"convert_to": "mp4"},
            "overrides": {"file_title": "{title_sanitized_plex}", "file_uid": "{uid_sanitized_plex}"},
        }, player=player)
    return Builtin(("_episode_base",), player=player)


def _ordering(**overrides: str) -> Builtin:
    return Builtin(config={"overrides": overrides})


def _format(height: int | None) -> Builtin:
    if height is None:
        return Builtin(config={"format": "bestvideo+bestaudio/best", "ytdl_options": {"merge_output_format": "mp4"}})
    return Builtin(config={
        "format": f"(bv*[height<={height}]+bestaudio/best[height<={height}])",
        "ytdl_options": {"merge_output_format": "mp4"},
    })


def _audio(codec: str, quality: int) -> Builtin:
    return Builtin(config={"audio_extract": {"codec": codec, "quality": quality}})


BY_DATE_ORDERINGS = {
    "season_by_year__episode_by_month_day": ("upload-year", "upload-month-day"),
    "season_by_year_month__episode_by_day": ("upload-year-month", "upload-day"),
    "season_by_year__episode_by_month_day_reversed": ("upload-year", "upload-month-day-reversed"),
    "season_by_year__episode_by_download_index": ("upload-year", "download-index"),
}
COLLECTION_ORDERINGS = {
    "season_by_collection__episode_by_year_month_day": "upload-year-month-day",
    "season_by_collection__episode_by_year_month_day_reversed": "upload-year-month-day-reversed",
    "season_by_collection__episode_by_playlist_index": "playlist-index",
    "season_by_collection__episode_by_playlist_index_reversed": "playlist-index-reversed",
}

BUILTINS: dict[str, Builtin] = {
    "_episode_base": _EPISODE_BASE,
    **{f"_{player}_tv_show": _player(player) for player in ("kodi", "jellyfin", "plex")},
    **{f"{player}_tv_show_by_date": Builtin((f"_{player}_tv_show",), kind="tv_show_by_date")
       for player in ("kodi", "jellyfin", "plex")},
    **{f"{player.title()} TV Show by Date": Builtin((f"{player}_tv_show_by_date", "season_by_year__episode_by_month_day"))
       for player in ("kodi", "jellyfin", "plex")},
    "Emby TV Show by Date": Builtin(("Jellyfin TV Show by Date",), player="emby"),
    **{f"{player}_tv_show_collection": Builtin((f"_{player}_tv_show",), kind="tv_show_collection")
       for player in ("kodi", "jellyfin", "plex")},
    **{f"{player.title()} TV Show Collection": Builtin(
        (f"{player}_tv_show_collection", "season_by_collection__episode_by_year_month_day"))
       for player in ("kodi", "jellyfin", "plex")},
    "Emby TV Show Collection": Builtin(("Jellyfin TV Show Collection",), player="emby"),
    **{name: _ordering(tv_show_by_date_season_ordering=season, tv_show_by_date_episode_ordering=episode)
       for name, (season, episode) in BY_DATE_ORDERINGS.items()},
    **{name: _ordering(tv_show_collection_episode_ordering=episode) for name, episode in COLLECTION_ORDERINGS.items()},
    "best_video_quality": _format(None),
    "Best Video Quality": Builtin(("best_video_quality",)),
    "Max Video Quality": Builtin(("best_video_quality",)),
    "Max 2160p": _format(2160),
    "Max 1440p": _format(1440),
    "max_1080p": _format(1080),
    "Max 1080p": Builtin(("max_1080p",)),
    "Max 720p": _format(720),
    "Max 480p": _format(480),
    "Max Audio Quality": _audio("best", 0),
    "Max MP3 Quality": _audio("mp3", 0),
    "Max Opus Quality": _audio("opus", 0),
    "MP3 320k": _audio("mp3", 320),
    "MP3 128k": _audio("mp3", 128),
    "Only Recent Archive": Builtin(config={
        "date_range": {"after": "today-{only_recent_date_range}"},
        "overrides": {"only_recent_date_range": "2months"},
    }),
    "Only Recent": Builtin(("Only Recent Archive",), {
        "output_options": {
            "keep_files_after": "today-{only_recent_date_range}",
            "keep_max_files": "{only_recent_max_files}",
        },
        "overrides": {"only_recent_max_files": 0, "only_recent_sort_by": "upload_date"},
    }),
    "chunk_initial_download": Builtin(config={
        "ytdl_options": {"max_downloads": "{chunk_max_downloads}", "playlistreverse": True, "break_on_existing": False},
        "overrides": {"chunk_max_downloads": 20},
    }),
    "Chunk Downloads": Builtin(("chunk_initial_download",)),
    "Filter Keywords": Builtin(config={"overrides": {
        "title_include_keywords": [], "title_exclude_keywords": [],
        "description_include_keywords": [], "description_exclude_keywords": [],
        "title_include_eval": "ANY", "title_exclude_eval": "ANY",
        "description_include_eval": "ANY", "description_exclude_eval": "ANY",
    }}),
    "Filter Duration": Builtin(config={"overrides": {"filter_duration_min_s": 0, "filter_duration_max_s": 4294967296}}),
    "_music_base": _MUSIC_BASE,
    "_albums_from_playlists": Builtin(("_music_base",), {"overrides": {
        "track_album": "{playlist_title}", "track_number": "{playlist_index}",
        "track_number_padded": "{playlist_index_padded}", "track_total": "{playlist_count}",
        "track_year": "{playlist_max_upload_year}",
    }}),
    "_albums_from_chapters": Builtin(("_music_base",), {"overrides": {
        "track_title": "{chapter_title}", "track_album": "{title}", "track_number": "{chapter_index}",
        "track_number_padded": "{chapter_index_padded}", "track_total": "{chapter_count}",
    }}),
    "YouTube Releases": Builtin(("_albums_from_playlists",), kind="music"),
    "YouTube Full Albums": Builtin(("_albums_from_chapters",), kind="music"),
    "Bandcamp": Builtin(("_albums_from_playlists",), kind="music"),
    "SoundCloud Discography": Builtin(("_music_base",), {"overrides": {
        "track_album": "{sc_track_album}", "track_number": "{sc_track_number}",
        "track_number_padded": "{sc_track_number_padded}", "track_total": "{sc_track_total}",
        "track_year": "{sc_track_year}",
    }}, kind="music"),
    "Single": Builtin(("_music_base",), kind="music"),
    "_music_video_base": _MUSIC_VIDEO_BASE,
    **{name: Builtin(("_music_video_base",), kind="music_video", player=player) for name, player in (
        ("Jellyfin Music Videos", "jellyfin"), ("Emby Music Videos", "emby"), ("Kodi Music Videos", "kodi"),
        ("Plex Music Videos", "plex"), ("Jellyfin Music Videos with Extras", "jellyfin"),
        ("Kodi Music Videos with Extras", "kodi"), ("Plex Music Videos with Extras", "plex"),
    )},
}
"""ytdl-sub's prebuilt presets by name."""

DOWNLOAD_HELPERS = frozenset({
    "Only Recent", "Only Recent Archive", "Chunk Downloads", "chunk_initial_download", "Filter Keywords",
    "Filter Duration",
})
"""Presets that only change which videos are downloaded: VODLoft's Download Profile, not its Local Media Profile."""
