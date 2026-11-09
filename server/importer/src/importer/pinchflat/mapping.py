"""What a Pinchflat installation becomes in VODLoft, as an :class:`ImportPlan`.

Each Pinchflat source becomes a yt-dlp Collection, each media profile a
Collection Local Media Profile with its converted template, and each source a
Download Profile for that pair. A source with its own template, or its own
option file, gets its own variant of the profile. Every downloaded item is
adopted at the path Pinchflat recorded: a rebuilt path can differ from the
real one when a title or template changed since.
"""
from __future__ import annotations

import re

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..contract import (
    CollectionPlan, CustomIndexPlan, FilePlan, ImportLocation, ImportPlan, ImportWarning, ProfilePlan, SettingPlan,
)
from ..paths import DEFAULT_PATH_MAP, PathMap, map_path
from ..uploads import UploadFile
from ..ytdlp_templates import (
    OptionError, OptionSet, convert_pinchflat, expand, load_options, options_from, pinchflat_option_files,
)
from ..ytdlp_templates.options import PINCHFLAT_META_DATE
from .metadata import saved_values
from .reader import PinchflatData, PinchflatItem, PinchflatProfile, PinchflatSource, read_pinchflat

PINCHFLAT_DOWNLOADS = "/downloads"
"""Pinchflat's download folder inside its container."""

_RESOLUTIONS = {
    "4320p": ("format_8k", "exact", None),
    "2160p": ("format_4k", "exact", None),
    "1440p": ("format_1440p", "exact", None),
    "1080p": ("format_1080p", "exact", None),
    "720p": ("format_720p", "exact", None),
    "480p": ("format_480p", "exact", None),
    "360p": ("format_360p", "exact", None),
    "audio": ("format_audio_only", "exact", None),
}
# Pinchflat prefers H.264 but takes any codec, which in VODLoft is Your own
# with H.264 first and every codec allowed.
_PREFER_H264 = [
    {"codec": "h264", "allowed": True}, {"codec": "vp9", "allowed": True},
    {"codec": "av1", "allowed": True}, {"codec": "h265", "allowed": True},
]
_LANGUAGE = re.compile(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})*")
_INDEX_FIELDS = {"playlist": "playlist_index", "day": "upload_date_index"}


@dataclass(frozen=True)
class _Variant:
    external_id: str
    name: str
    base_name: str | None
    profile: PinchflatProfile
    template: str
    files: tuple
    sources: tuple[PinchflatSource, ...]


def _has_option_file(directory: Path | None, source: PinchflatSource) -> bool:
    if directory is None:
        return False
    path = directory / f"source-{source.id}-config.txt"
    return path.is_file() and path.stat().st_size > 0


def _variants(data: PinchflatData, directory: Path | None) -> list[_Variant]:
    profiles = {profile.id: profile for profile in data.profiles}
    groups: dict[str, _Variant] = {}
    for source in data.sources:
        profile = profiles.get(source.media_profile_id)
        if profile is None or source.marked_for_deletion:
            continue
        own = bool(source.output_path_template_override) or _has_option_file(directory, source)
        external_id = f"media_profile:{profile.id}" + (f":source:{source.id}" if own else "")
        files = pinchflat_option_files(directory, media_profile_id=profile.id, source_id=source.id if own else None) \
            if directory is not None else ()
        current = groups.get(external_id)
        groups[external_id] = _Variant(
            external_id,
            f"{profile.name} ({source.name})" if own else profile.name,
            profile.name if own else None,
            profile,
            source.output_path_template_override or profile.output_path_template,
            files,
            (*(current.sources if current else ()), source),
        )
    return list(groups.values())


def command_line(profile: PinchflatProfile, data: PinchflatData, template: str) -> list[str]:
    """The options Pinchflat passes yt-dlp for a download with this profile, as far as they matter here."""
    args = ["--no-progress", "--windows-filenames", "--parse-metadata", PINCHFLAT_META_DATE[0]]
    if data.settings.restrict_filenames:
        args.append("--restrict-filenames")
    if profile.preferred_resolution == "audio":
        args += ["-f", "bestaudio/best", "-x", "--audio-format", "best"]
    else:
        height = (profile.preferred_resolution or "1080p").removesuffix("p")
        args += ["-f", "bestvideo*+bestaudio/best", "-S", f"res:{height}"]
        if profile.media_container:
            args += ["--remux-video", profile.media_container]
    if profile.download_subs:
        args += ["--write-subs", "--convert-subs", "srt"]
        if profile.sub_langs:
            args += ["--sub-langs", profile.sub_langs]
    if profile.download_auto_subs:
        args.append("--write-auto-subs")
    if profile.embed_subs and profile.preferred_resolution != "audio":
        args.append("--embed-subs")
    if profile.download_thumbnail:
        args += ["--write-thumbnail", "--convert-thumbnails", "jpg"]
    if profile.embed_thumbnail:
        args.append("--embed-thumbnail")
    if profile.download_metadata:
        args += ["--write-info-json", "--clean-info-json"]
    if profile.embed_metadata:
        args.append("--embed-metadata")
    if profile.sponsorblock_behaviour == "remove" and profile.sponsorblock_categories:
        args += ["--sponsorblock-remove", ",".join(profile.sponsorblock_categories)]
    elif profile.sponsorblock_behaviour == "mark" and profile.sponsorblock_categories:
        args += ["--sponsorblock-mark", ",".join(profile.sponsorblock_categories)]
    args += ["-o", f"{PINCHFLAT_DOWNLOADS}/{expand(template).lstrip('/')}"]
    return args


def _profile_warnings(profile: PinchflatProfile) -> list[ImportWarning]:
    warnings: list[ImportWarning] = []
    resolution = _RESOLUTIONS.get(profile.preferred_resolution or "1080p")
    if resolution is None:
        warnings.append(ImportWarning("preferred_resolution", f"VODLoft has no {profile.preferred_resolution}; it downloads 1080p"))
    elif resolution[1] != "exact":
        warnings.append(ImportWarning("preferred_resolution", resolution[2], resolution[1]))
    _languages, left_out = _subtitle_languages(profile.sub_langs)
    if profile.download_subs and left_out:
        warnings.append(ImportWarning(
            "sub_langs", f"VODLoft lists languages by code, so it leaves out {', '.join(left_out)}", "close",
        ))
    if _audio_language(profile.audio_track) is None and (profile.audio_track or "") not in ("", "default", "original"):
        warnings.append(ImportWarning("audio_track", f"VODLoft chooses audio by language code, not {profile.audio_track}; it keeps the original"))
    if profile.media_container and profile.media_container not in ("mp4", "mkv"):
        warnings.append(ImportWarning(
            "media_container", f"VODLoft downloads MP4 or MKV, not {profile.media_container}; new downloads are MKV",
            "close",
        ))
    return warnings


def _subtitle_languages(sub_langs: str | None) -> tuple[list[str], list[str]]:
    """Pinchflat's yt-dlp --sub-langs as language codes, and the parts that are no language code.

    No list, or "all", is every language the site offers. A pattern such as
    en.* becomes en, which VODLoft also matches with its regional variants.
    """
    languages: list[str] = []
    left_out: list[str] = []
    for part in (sub_langs or "").split(","):
        part = part.strip()
        if not part or part == "all" or part.startswith("-"):
            continue
        code = re.sub(r"(\.\*|\.\+|-\.\*|\*)$", "", part)
        if _LANGUAGE.fullmatch(code) and code not in languages:
            languages.append(code)
        elif not _LANGUAGE.fullmatch(code):
            left_out.append(part)
    return languages, left_out


def _audio_language(audio_track: str | None) -> str | None:
    """Pinchflat's audio track as a language code; default and original keep the original language."""
    track = (audio_track or "").strip()
    return track if track not in ("default", "original") and _LANGUAGE.fullmatch(track) else None


def _quality_settings(profile: PinchflatProfile) -> dict[str, object]:
    """Pinchflat's container, audio track and subtitle languages as Local Media Profile choices."""
    languages, _left_out = _subtitle_languages(profile.sub_langs)
    settings: dict[str, object] = {
        "subtitle_languages": languages or ["en"],
        "subtitle_language_mode": "listed" if languages else "site",
        "audio_language": _audio_language(profile.audio_track),
    }
    container = profile.media_container if profile.media_container in ("mp4", "mkv") else "mkv" if profile.media_container else "mp4"
    # Above 1080p there is rarely H.264, so only a lower resolution in MP4 is Compatibility.
    if container == "mp4" and profile.preferred_resolution not in ("1440p", "2160p", "4320p"):
        settings["quality_goal"] = "compatibility"
    else:
        settings.update(quality_goal="custom", video_codecs=_PREFER_H264, container=container, audio_codec="aac")
    return settings


def _template_root(template: str, path_map: PathMap) -> tuple[str, str, str | None]:
    """The template relative to VODLoft's folder for Pinchflat's /downloads, and that folder."""
    source, target = path_map
    if source == PINCHFLAT_DOWNLOADS:
        return template, target.rstrip("/") + "/", None
    inner = "/" + str(PurePosixPath(source).relative_to(PINCHFLAT_DOWNLOADS)) + "/"
    stripped = "/" + template.lstrip("/")
    if stripped.startswith(inner):
        return stripped[len(inner) - 1:], target.rstrip("/") + "/", None
    return template, "/downloads/", (
        f"The template starts outside {source}, which VODLoft can't see; new downloads go under /downloads/ instead"
    )


# Options the converter explains better than a yt-dlp option could: the template and links.
_NOT_FORWARDED = frozenset({"outtmpl", "url"})


def _profile_plan(variant: _Variant, data: PinchflatData, path_map: PathMap) -> tuple[ProfilePlan, str]:
    """The Local Media Profile, and the option file lines VODLoft has no setting for, for its Collections."""
    profile = variant.profile
    warnings = _profile_warnings(profile)
    try:
        option_set: OptionSet | None = load_options(variant.files, command_line(profile, data, variant.template))
    except (OptionError, ValueError) as exc:
        option_set = None
        warnings.append(ImportWarning("option files", f"yt-dlp refuses the option files: {exc}"))
    types = {source.collection_type for source in variant.sources}
    template, root, problem = _template_root(variant.template, path_map)
    if problem:
        warnings.append(ImportWarning("output template", problem, "close"))
    options = options_from(
        option_set, root=root, collection_type=next(iter(types)) if len(types) == 1 else None,
        for_playlists="playlist" in types,
    ) if option_set is not None else None
    report = convert_pinchflat(template, options)

    custom: list[str] = []
    settings: dict[str, object] = {
        "preferred_format": (_RESOLUTIONS.get(profile.preferred_resolution or "1080p") or ("format_1080p",))[0],
        "collection_scope": "both",
        **_quality_settings(profile),
    }
    if option_set is not None:
        settings.update({
            key: option_set.profile_settings[key]
            for key in ("subtitle_mode", "thumbnail_mode") if key in option_set.profile_settings
        })
        embed = option_set.profile_settings.get("metadata_mode") == "embed"
        settings["metadata_mode"] = (
            "embed_and_nfo" if embed and profile.download_nfo else "nfo" if profile.download_nfo
            else "embed" if embed else "no_metadata"
        )
        for option in option_set.reports:
            if option.option.origin == "Pinchflat":
                continue
            if option.handling == "unsupported" and option.option.dest not in _NOT_FORWARDED:
                # VODLoft checks these as your own yt-dlp options, and reports the lines it can't use.
                custom.append(f"{option.option.source}  # {option.option.origin}")
            elif option.handling in ("unsupported", "close"):
                warnings.append(ImportWarning(
                    option.option.origin, f"{option.option.source}: {option.reason}",
                    "close" if option.handling == "close" else "unsupported",
                ))
    if profile.preferred_resolution == "audio":
        settings["subtitle_mode"] = "no_subtitles"
    settings["download_collection_assets"] = bool(profile.download_source_images)
    if report.output_template is None:
        warnings.append(ImportWarning("output template", "; ".join(report.errors) or "The template could not be converted"))
    return ProfilePlan(
        external_id=variant.external_id,
        name=variant.name,
        output_template=report.output_template,
        custom_indexes=report.custom_indexes,
        settings=settings,
        warnings=tuple(warnings),
        original_template=variant.template,
        report=tuple(report.lines()[1:]),
        support=report.support,
        base_name=variant.base_name,
    ), "\n".join(custom)


def _episode_types(profile: PinchflatProfile) -> list[str]:
    only = [tag for tag, behaviour in (("short", profile.shorts_behaviour), ("livestream", profile.livestream_behaviour))
            if behaviour == "only"]
    if only:
        return only
    types = ["ep"]
    if profile.shorts_behaviour == "include":
        types.append("short")
    if profile.livestream_behaviour == "include":
        types.append("livestream")
    return types


SPONSORBLOCK_CATEGORIES = (
    "sponsor", "selfpromo", "interaction", "intro", "outro", "preview", "filler", "hook", "music_offtopic",
)


def _sponsorblock(profile: PinchflatProfile) -> dict[str, object]:
    """Pinchflat's SponsorBlock setting: remove or mark the chosen categories, keep the others."""
    on = profile.sponsorblock_behaviour in ("remove", "mark") and bool(profile.sponsorblock_categories)
    action = "cut" if profile.sponsorblock_behaviour == "remove" else "chapter"
    chosen = set(profile.sponsorblock_categories)
    return {
        "sponsorblock_enabled": on,
        "sponsorblock_segments": {
            **{category: action if on and category in chosen else "keep" for category in SPONSORBLOCK_CATEGORIES},
            # Pinchflat has no choice for these. VODLoft always marked the highlight; viewer chapters stay out.
            "poi_highlight": "chapter" if on else "keep",
            "chapter": "keep",
        },
    }


_COOKIES = {"disabled": "never", "when_needed": "automatic", "all_operations": "always"}
"""Pinchflat's cookie behaviour as VODLoft's per-Collection cookies choice."""

PINCHFLAT_INDEX_MINUTES = 24 * 60
"""Pinchflat lists a source once a day unless told otherwise."""


def _checking(source: PinchflatSource, warnings: list[ImportWarning]) -> dict[str, object]:
    """Pinchflat's index frequency, as a Collection's own schedule only when it checked less often than daily.

    VODLoft checks YouTube channels more often than Pinchflat's daily default on its own, so a source indexed
    daily or more often keeps VODLoft's default.

    Fast indexing overrides the index frequency, and VODLoft's quick check is its counterpart, so such a source
    keeps the default too. It says so explicitly where the frequency alone would have given it its own schedule,
    so that running the import again takes back a schedule an earlier import set.
    """
    minutes = source.index_frequency_minutes
    if minutes is None or 0 < minutes <= PINCHFLAT_INDEX_MINUTES:
        return {}
    if source.fast_index:
        return {"check_frequency": "default"}
    if minutes < 0:
        warnings.append(ImportWarning(
            "index_frequency_minutes",
            "Pinchflat never looked for new videos in this source; VODLoft does, so turn its Download Profile off "
            "if nothing new should be downloaded", "close",
        ))
        return {}
    days = max(2, round(minutes / PINCHFLAT_INDEX_MINUTES))
    return {"check_frequency": "own", "check_cron": f"0 4 */{days} * *"}


def _collection_plan(source: PinchflatSource, profile: PinchflatProfile, profile_external_id: str, path_map: PathMap,
                     ytdlp_options: str = "") -> CollectionPlan:
    warnings: list[ImportWarning] = []
    limits: dict[str, object] = {"download_days_in_past": 0, "download_episode_count": 0,
                                 "download_starting_from": None, "delete_older_episodes": False,
                                 "retention_from": "published"}
    if source.retention_period_days:
        limits.update(download_days_in_past=source.retention_period_days, delete_older_episodes=True,
                      retention_from="downloaded")
        warnings.append(ImportWarning(
            "retention_period_days",
            f"Downloads are deleted {source.retention_period_days} days after downloading, like Pinchflat did, and "
            f"only videos from the last {source.retention_period_days} days are downloaded", "close",
        ))
        if source.download_cutoff_date:
            warnings.append(ImportWarning(
                "download_cutoff_date",
                f"VODLoft limits by age or by date, not both; the {source.retention_period_days} days win over "
                f"{source.download_cutoff_date}", "close",
            ))
    elif source.download_cutoff_date:
        limits["download_starting_from"] = source.download_cutoff_date[:10]
    rules: list[dict[str, object]] = []
    if source.title_filter_regex:
        # Pinchflat downloads only the videos whose title matches, ignoring case, anywhere in the title.
        try:
            re.compile(source.title_filter_regex)
        except re.error as exc:
            warnings.append(ImportWarning("title_filter_regex", f"The title filter is not a pattern VODLoft can read ({exc})"))
        else:
            rules.append({"action": "only", "field": "title", "pattern": source.title_filter_regex, "ignore_case": False})
    if source.min_duration_seconds:
        rules.append({"action": "skip", "field": "duration", "duration_operator": "shorter",
                      "duration_seconds": source.min_duration_seconds})
    if source.max_duration_seconds:
        rules.append({"action": "skip", "field": "duration", "duration_operator": "longer",
                      "duration_seconds": source.max_duration_seconds})
    checking = _checking(source, warnings)
    upgrade: dict[str, object] = {}
    if profile.redownload_delay_days:
        # Pinchflat downloads once more after the delay; the upgrade check does too, but keeps the better file.
        upgrade = {"upgrade_check": True, "upgrade_after_days": profile.redownload_delay_days, "upgrade_repeat": "once"}
        warnings.append(ImportWarning(
            "redownload_delay_days",
            f"The upgrade check looks again {profile.redownload_delay_days} days after downloading, and replaces the "
            "file only when the new one is better", "close",
        ))
    audio = profile.preferred_resolution == "audio"
    assets = tuple(
        (kind, mapped) for kind, path in (
            ("poster", source.poster_filepath), ("fanart", source.fanart_filepath),
            ("banner", source.banner_filepath), ("nfo", source.nfo_filepath),
        ) if (mapped := map_path(path, path_map))
    )
    return CollectionPlan(
        external_id=f"source:{source.id}",
        url=source.original_url,
        title=source.name,
        profile_external_id=profile_external_id,
        settings={"type": "podcast" if audio else "series", "episode_identifier": "date_based",
                  "collection_type": source.collection_type,
                  # A channel's name is its author; the path proof fills {{ channel }} with it.
                  **({"author": source.collection_name}
                     if source.collection_type == "channel" and source.collection_name else {}),
                  # VODLoft checks these as the Collection's own yt-dlp options, and reports the lines it can't use.
                  **({"ytdlp_options": ytdlp_options} if ytdlp_options else {}),
                  "cookies_mode": _COOKIES.get(source.cookie_behaviour or "disabled", "never"),
                  **checking},
        download_profile={
            "enable_profile": source.enabled and source.download_media,
            "ep_id_type_list": _episode_types(profile),
            "download_with_countdown": False, "redownload_final": False,
            "seasons": [], "include_upcoming_seasons": True,
            "rules": rules,
            # yt-dlp takes an uploaded subtitle over an auto-generated one, as VODLoft's fallback does.
            "auto_subtitles": "fallback" if profile.download_auto_subs else "never",
            **_sponsorblock(profile),
            **upgrade,
            **limits,
        },
        warnings=tuple(warnings),
        assets=assets,
        added_at=source.added_at,
    )


def _file_plan(item: PinchflatItem, source: PinchflatSource, indexes: Sequence[CustomIndexPlan], path_map: PathMap,
               saved: Mapping[str, str] | None = None) -> FilePlan | None:
    external_id = f"source:{source.id}"
    if item.culled_at:
        return FilePlan(external_id, item.media_id, None, "missing", title=item.title, published=item.uploaded_at)
    path = map_path(item.media_filepath, path_map)
    if path is not None:
        values: dict[str, int] = {}
        for index in indexes:
            field = _INDEX_FIELDS.get(index.key)
            value = getattr(item, field) if field else None
            if value is None:
                continue
            ordinal = index.ordinal(value)
            if ordinal is not None:
                values[index.key] = ordinal
        return FilePlan(external_id, item.media_id, path, "file", values, item.title, item.uploaded_at,
                        kept=item.prevent_culling, episode_values=dict(saved or {}))
    if item.prevent_download:
        return FilePlan(external_id, item.media_id, None, "suppressed", title=item.title, published=item.uploaded_at)
    return None


def _settings(data: PinchflatData, extras: Path | None) -> list[SettingPlan]:
    settings = [SettingPlan(
        "downloads.filename_restriction_mode", "restricted" if data.settings.restrict_filenames else "windows",
        note="Pinchflat's Restrict filenames setting becomes VODLoft's filename mode for every download",
    )]
    if data.settings.youtube_api_key:
        settings.append(SettingPlan("ytdlp.youtube_api_key", data.settings.youtube_api_key, secret=True,
                                    note="VODLoft looks channels and playlists up with it"))
    cookies = extras / "cookies.txt" if extras is not None else None
    if cookies is not None and cookies.is_file() and cookies.stat().st_size > 0:
        settings.append(SettingPlan("ytdlp.cookies", str(cookies), secret=True,
                                    note="It holds a sign-in; VODLoft deletes the uploaded copy once it is used"))
    if data.settings.extractor_sleep_interval_seconds:
        settings.append(SettingPlan("extractor_sleep_interval_seconds", data.settings.extractor_sleep_interval_seconds,
                                    "close", "VODLoft paces its own requests to YouTube"))
    limit = _megabytes_per_second(data.settings.download_throughput_limit)
    if limit is not None:
        settings.append(SettingPlan(
            "settings.download_settings.speed_limit_mode", "custom",
            note="Pinchflat limited download speed, so VODLoft does too",
        ))
        settings.append(SettingPlan(
            "settings.download_settings.speed_limit_mbps", limit,
            note=f"Pinchflat's {data.settings.download_throughput_limit} for all downloads together",
        ))
    elif data.settings.download_throughput_limit:
        settings.append(SettingPlan("download_throughput_limit", data.settings.download_throughput_limit, "unsupported",
                                    "Not a speed VODLoft can read; set one in Settings › Downloads"))
    if data.settings.apprise_server:
        settings.append(SettingPlan(
            "notifications.apprise", data.settings.apprise_server, secret=True,
            note="Becomes the destination Pinchflat in Messages and actions, added to the default rules",
        ))
    if extras is not None and (extras / "user-scripts" / "lifecycle").is_file():
        settings.append(SettingPlan(
            "lifecycle_script", None, "unsupported",
            "Scripts run code, so VODLoft does not copy them. Put it in /config/scripts and add it as a script "
            "action in Settings › Messages and actions",
        ))
    return settings


_RATE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgKMG]?)(?:i?[bB])?\s*$")


def _megabytes_per_second(rate: str | None) -> float | None:
    """yt-dlp's --limit-rate, such as 4.2M or 500K (powers of 1024), in VODLoft's MB/s."""
    match = _RATE.match(rate or "")
    if not match:
        return None
    number = float(match.group(1)) * 1024 ** " KMG".index(match.group(2).upper() or " ")
    return max(round(number / 1_000_000, 2), 0.01) if number > 0 else None


def plan_import(data: PinchflatData, *, option_directory: Path | None, extras: Path | None = None,
                path_map: PathMap = DEFAULT_PATH_MAP, saved: Mapping[int, Mapping[str, str]] | None = None) -> ImportPlan:
    variants = _variants(data, option_directory)
    planned = [_profile_plan(variant, data, path_map) for variant in variants]
    profiles = [plan for plan, _custom in planned]
    by_source: dict[int, tuple[ProfilePlan, PinchflatProfile, str]] = {
        source.id: (plan, variant.profile, custom)
        for variant, (plan, custom) in zip(variants, planned, strict=True) for source in variant.sources
    }
    collections: list[CollectionPlan] = []
    files: list[FilePlan] = []
    items_by_source: dict[int, list[PinchflatItem]] = {}
    for item in data.items:
        items_by_source.setdefault(item.source_id, []).append(item)
    for source in data.sources:
        if source.id not in by_source:
            continue
        plan, profile, custom = by_source[source.id]
        collections.append(_collection_plan(source, profile, plan.external_id, path_map, custom))
        for item in items_by_source.get(source.id, ()):
            file_plan = _file_plan(item, source, plan.custom_indexes, path_map, (saved or {}).get(item.id))
            if file_plan is not None:
                files.append(file_plan)
    warnings = [ImportWarning(
        "Pinchflat", "If Pinchflat keeps downloading these channels into the same folders, you get duplicates. "
        "Pause its sources in Pinchflat, or leave the imported Download Profiles off for now.", "close",
    )]
    skipped = [source for source in data.sources if source.id not in by_source]
    for source in skipped:
        warnings.append(ImportWarning(source.name, "Not imported: Pinchflat is deleting this source or its media profile"))
    unmapped = sum(1 for item in data.items if item.media_filepath and map_path(item.media_filepath, path_map) is None)
    if unmapped:
        warnings.append(ImportWarning("files", f"{unmapped} files are outside Pinchflat's /downloads folder and are not adopted"))
    return ImportPlan(
        importer="pinchflat",
        profiles=tuple(profiles),
        collections=tuple(collections),
        files=tuple(files),
        settings=tuple(_settings(data, extras)),
        warnings=tuple(warnings),
        version=str(data.version),
    )


UPLOAD_FILES = (
    UploadFile("db/pinchflat.db", required=True),
    UploadFile("db/pinchflat.db-wal"),
    UploadFile("extras/yt-dlp-configs/*.txt"),
    UploadFile("extras/cookies.txt", secret=True),
    # Only to tell that there is one: VODLoft never copies or runs it.
    UploadFile("extras/user-scripts/lifecycle"),
    # The yt-dlp metadata of each video, for values such as the uploader; the thumbnails next to it are left out.
    UploadFile("metadata/media_items/*/metadata.json.gz"),
)
"""What a Pinchflat upload takes from its /config folder."""


class PinchflatImporter:
    key = "pinchflat"
    name = "Pinchflat"
    upload_files = UPLOAD_FILES
    database = "db/pinchflat.db"
    extras = "extras"

    def read(self, location: ImportLocation) -> ImportPlan:
        data = read_pinchflat(location.database)
        directory = location.extras / "yt-dlp-configs" if location.extras is not None else None
        return plan_import(
            data, option_directory=directory if directory is not None and directory.is_dir() else None,
            extras=location.extras, path_map=location.path_map,
            saved=saved_values(location.folder, data.metadata_files),
        )
