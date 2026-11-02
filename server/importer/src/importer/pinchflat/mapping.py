"""What a Pinchflat installation becomes in VODLoft, as an :class:`ImportPlan`.

Each Pinchflat source becomes a yt-dlp Collection, each media profile a
Collection Local Media Profile with its converted template, and each source a
Download Profile for that pair. A source with its own template, or its own
option file, gets its own variant of the profile. Every downloaded item is
adopted at the path Pinchflat recorded: a rebuilt path can differ from the
real one when a title or template changed since.
"""
from __future__ import annotations

from collections.abc import Sequence
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
from .reader import PinchflatData, PinchflatItem, PinchflatProfile, PinchflatSource, read_pinchflat

PINCHFLAT_DOWNLOADS = "/downloads"
"""Pinchflat's download folder inside its container."""

_RESOLUTIONS = {
    "4320p": ("format_4k", "close", "VODLoft's best quality is 4K"),
    "2160p": ("format_4k", "exact", None),
    "1440p": ("format_1080p", "unsupported", "VODLoft has no 1440p yet, so new downloads are 1080p until it does"),
    "1080p": ("format_1080p", "exact", None),
    "720p": ("format_720p", "exact", None),
    "480p": ("format_720p", "close", "VODLoft's lowest video quality is 720p"),
    "360p": ("format_720p", "close", "VODLoft's lowest video quality is 720p"),
    "audio": ("format_audio_only", "exact", None),
}
_INDEX_FIELDS = {"playlist": "playlist_index", "day": "upload_date_index"}


@dataclass(frozen=True)
class _Variant:
    external_id: str
    name: str
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
    if profile.download_auto_subs:
        warnings.append(ImportWarning("download_auto_subs", "VODLoft downloads only subtitles a person uploaded, not automatic ones yet"))
    if profile.download_subs and profile.sub_langs and profile.sub_langs.strip() not in ("", "all"):
        warnings.append(ImportWarning(
            "sub_langs", f"VODLoft downloads every uploaded language, not only {profile.sub_langs}", "close",
        ))
    if profile.sponsorblock_behaviour not in (None, "", "disabled"):
        warnings.append(ImportWarning("sponsorblock_behaviour", "VODLoft does not use SponsorBlock yet"))
    if profile.redownload_delay_days:
        warnings.append(ImportWarning(
            "redownload_delay_days", f"VODLoft does not download a video again after {profile.redownload_delay_days} days yet",
        ))
    if profile.audio_track and profile.audio_track not in ("", "default"):
        warnings.append(ImportWarning("audio_track", f"VODLoft does not choose an audio track ({profile.audio_track}) yet"))
    if profile.media_container:
        warnings.append(ImportWarning(
            "media_container", f"New downloads use VODLoft's container instead of {profile.media_container}; existing files keep theirs",
            "close",
        ))
    return warnings


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


def _profile_plan(variant: _Variant, data: PinchflatData, path_map: PathMap) -> ProfilePlan:
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
    options = options_from(option_set, root=root, collection_type=types.pop() if len(types) == 1 else None) \
        if option_set is not None else None
    report = convert_pinchflat(template, options)

    settings: dict[str, object] = {
        "preferred_format": (_RESOLUTIONS.get(profile.preferred_resolution or "1080p") or ("format_1080p",))[0],
        "collection_scope": "both",
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
            if option.option.origin != "Pinchflat" and option.handling in ("unsupported", "close"):
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
    )


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


def _collection_plan(source: PinchflatSource, profile: PinchflatProfile, profile_external_id: str, path_map: PathMap) -> CollectionPlan:
    warnings: list[ImportWarning] = []
    limits: dict[str, object] = {"download_days_in_past": 0, "download_episode_count": 0,
                                 "download_starting_from": None, "delete_older_episodes": False}
    if source.retention_period_days:
        limits.update(download_days_in_past=source.retention_period_days, delete_older_episodes=True)
        warnings.append(ImportWarning(
            "retention_period_days",
            f"New downloads older than {source.retention_period_days} days are deleted, like Pinchflat did. "
            "Imported files are never deleted by it", "close",
        ))
        if source.download_cutoff_date:
            warnings.append(ImportWarning(
                "download_cutoff_date",
                f"VODLoft limits by age or by date, not both; the {source.retention_period_days} days win over "
                f"{source.download_cutoff_date}", "close",
            ))
    elif source.download_cutoff_date:
        limits["download_starting_from"] = source.download_cutoff_date[:10]
    if source.title_filter_regex:
        warnings.append(ImportWarning("title_filter_regex", "VODLoft does not filter videos by title yet"))
    if source.min_duration_seconds or source.max_duration_seconds:
        warnings.append(ImportWarning("duration", "VODLoft does not filter videos by length yet"))
    if source.cookie_behaviour not in (None, "", "disabled"):
        warnings.append(ImportWarning("cookie_behaviour", "VODLoft uses its cookies for every video or none, not per Collection yet"))
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
                  "collection_type": source.collection_type},
        download_profile={
            "enable_profile": source.enabled and source.download_media,
            "ep_id_type_list": _episode_types(profile),
            "download_with_countdown": False, "redownload_final": False,
            "seasons": [], "include_upcoming_seasons": True,
            **limits,
        },
        warnings=tuple(warnings),
        assets=assets,
    )


def _file_plan(item: PinchflatItem, source: PinchflatSource, indexes: Sequence[CustomIndexPlan], path_map: PathMap) -> FilePlan | None:
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
        return FilePlan(external_id, item.media_id, path, "file", values, item.title, item.uploaded_at)
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
    if data.settings.download_throughput_limit:
        settings.append(SettingPlan("download_throughput_limit", data.settings.download_throughput_limit,
                                    "unsupported", "VODLoft has no download speed limit yet"))
    if data.settings.apprise_configured:
        settings.append(SettingPlan("apprise_server", None, "unsupported", "VODLoft does not send notifications yet"))
    return settings


def plan_import(data: PinchflatData, *, option_directory: Path | None, extras: Path | None = None,
                path_map: PathMap = DEFAULT_PATH_MAP) -> ImportPlan:
    variants = _variants(data, option_directory)
    profiles = [_profile_plan(variant, data, path_map) for variant in variants]
    by_source: dict[int, tuple[ProfilePlan, PinchflatProfile]] = {
        source.id: (plan, variant.profile)
        for variant, plan in zip(variants, profiles, strict=True) for source in variant.sources
    }
    collections: list[CollectionPlan] = []
    files: list[FilePlan] = []
    items_by_source: dict[int, list[PinchflatItem]] = {}
    for item in data.items:
        items_by_source.setdefault(item.source_id, []).append(item)
    for source in data.sources:
        if source.id not in by_source:
            continue
        plan, profile = by_source[source.id]
        collections.append(_collection_plan(source, profile, plan.external_id, path_map))
        for item in items_by_source.get(source.id, ()):
            file_plan = _file_plan(item, source, plan.custom_indexes, path_map)
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
)
"""What a Pinchflat upload takes from its /config folder; its metadata folder of thumbnails is left out."""


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
        )
