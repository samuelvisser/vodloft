"""What a WebDAV stream profile's share holds: a folder per show, laid out the way media players read a TV show.

A show's folder holds its episodes, sorted into a folder per season, per year or none, each named
``<Show> - S01E05 - <Title>`` or ``<Show> - 2026-03-15 - <Title>``. Only downloaded episodes are listed, as a
player seeks in a whole file; a share never streams from the Site. Beside them,
as the profile chooses, are NFO files and artwork, made when they are asked for: nothing is written next
to the downloads.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from sqlalchemy.orm import Session

from backend.db.datetime_types import utc_datetime
from backend.db.models import Collection, Episode
from backend.db.models.stream_profile import WebdavStreamProfile
from backend.services.collection_assets import collection_asset_sources
from backend.services.download_metadata import build_episode_metadata, build_season_metadata, build_show_metadata
from backend.services.stream_episodes import get_stream_items
from backend.services.stream_tokens import profiles_for_token
from backend.services.thumbnails import own_thumbnail_file
from backend.services.video_cache import artwork_cache_path, mark_used
from backend.utils.collection_asset_files import download_collection_asset
from config import get_settings
from backend.types.stream_profile_types import WebdavMetadataFiles, WebdavSeasonFolders
from backend.utils.output_template import sanitize_path_component
from config.settings.submodels import FilenameRestrictionMode
from backend.types.download_profile_types import EpIdType
from backend.types.episode_types import EpisodeExtraType
from backend.types.season_types import SeasonType
from downloader.metadata import MediaServerMetadata, render_nfo

_EXTENSIONS = {"mp4": ".mp4", "audio": ".m4a"}
_CONTENT_TYPES = {".mp4": "video/mp4", ".m4a": "audio/mp4", ".nfo": "text/xml", ".jpg": "image/jpeg", ".png": "image/png"}


@dataclass(frozen=True)
class Artwork:
    """A picture a share lists, fetched when a player asks for it: a picture VODLoft made, or one elsewhere."""

    url: str
    image_format: str = "jpg"


@dataclass
class ShareFile:
    name: str
    modified: datetime
    path: Optional[Path] = None
    content: Optional[bytes] = None
    artwork: Optional[Artwork] = None

    @property
    def content_type(self) -> str:
        return _CONTENT_TYPES.get(Path(self.name).suffix, "application/octet-stream")


@dataclass
class ShareFolder:
    name: str
    modified: datetime
    children: dict[str, Union["ShareFolder", ShareFile]] = field(default_factory=dict)

    def add(self, node: Union["ShareFolder", ShareFile]) -> None:
        """Add ``node``, renamed ``<name> (2)`` and so on when the folder already holds that name."""
        stem, suffix = (node.name, "") if isinstance(node, ShareFolder) else (Path(node.name).stem, Path(node.name).suffix)
        number = 1
        while node.name.lower() in (name.lower() for name in self.children):
            number += 1
            node.name = f"{stem} ({number}){suffix}"
        self.children[node.name] = node
        self.modified = max(self.modified, node.modified)

    def folder(self, name: str, modified: datetime) -> "ShareFolder":
        existing = self.children.get(name)
        if isinstance(existing, ShareFolder):
            return existing
        child = ShareFolder(name, modified)
        self.add(child)
        return child


def artwork_file(artwork: Artwork, *, fetch: bool) -> Optional[Path]:
    """The picture's file: VODLoft's own, or one in the Stream Video Cache, fetched first when ``fetch`` asks."""
    own = own_thumbnail_file(artwork.url)
    if own is not None:
        return own
    target = artwork_cache_path(artwork.url, artwork.image_format)
    if target.is_file():
        if fetch:
            mark_used(target)
        return target
    if not fetch:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as workspace:
        prepared = download_collection_asset(
            artwork.url, Path(workspace), ffmpeg_path=get_settings().download_settings.ffmpeg_path,
            fallback_format=artwork.image_format, forced_format=artwork.image_format, check_canceled=lambda: None,
        )
        os.replace(prepared.path, target)
    return target


def shows_for_token(s: Session, token: str) -> list[WebdavStreamProfile]:
    """The enabled shows a share address opens: one profile's own, or all of a user's."""
    return profiles_for_token(s, token, WebdavStreamProfile, what="Share")


def _name(value: str) -> str:
    # Windows' rules, as players on any system may open the share.
    return sanitize_path_component(value, mode=FilenameRestrictionMode.WINDOWS).strip() or "Untitled"


def show_name(profile: WebdavStreamProfile) -> str:
    return _name(profile.overwrite_collection_title or profile.collection.title)


def _modified(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def _aired(episode: Episode) -> Optional[datetime]:
    moment = episode.published_date or episode.went_live_date
    return utc_datetime(moment) if moment is not None else None


# Media players keep a show's specials in season 0, in a folder of their own, and its trailers in a Trailers folder.
_SPECIALS = "Specials"
_TRAILERS = "Trailers"
_OTHER = "Other"
_SPECIALS_SEASON = MediaServerMetadata(kind="season", title=_SPECIALS, season_number=0)


def _is_special(episode: Episode) -> bool:
    """Whether the episode is a special, as the Media Server output templates tell: an episode of an extra season
    or an auxiliary episode. A trailer is listed as one of the show's trailers instead."""
    season = episode.season
    return (season is not None and season.season_type == SeasonType.EXTRA.value) or episode.episode_type == EpIdType.AUX


def _episode_metadata(episode: Episode, by_number: bool) -> MediaServerMetadata:
    """What the episode's NFO file and name say about it. A show numbered by season keeps its specials in
    season 0, as their numbers count on their own."""
    metadata = build_episode_metadata(episode, episode.collection)
    return replace(metadata, season_number=0) if by_number and _is_special(episode) else metadata


def _episode_base_name(show: str, episode: Episode, metadata: MediaServerMetadata, by_number: bool) -> str:
    if by_number and metadata.season_number is not None and metadata.episode_number is not None:
        label = f"S{metadata.season_number:02d}E{metadata.episode_number:02d}"
    else:
        aired = _aired(episode)
        label = aired.strftime("%Y-%m-%d") if aired else f"E{episode.index:02d}"
    return f"{show} - {label} - {_name(episode.title)}"


def _season_folder(
    parent: ShareFolder, profile: WebdavStreamProfile, episode: Episode, metadata: MediaServerMetadata,
    modified: datetime,
) -> ShareFolder:
    layout = WebdavSeasonFolders(profile.season_folders)
    if layout is WebdavSeasonFolders.SEASON:
        if metadata.season_number == 0:
            return parent.folder(_SPECIALS, modified)
        return parent.folder(f"Season {episode.season.season_number:02d}", modified)
    if layout is WebdavSeasonFolders.YEAR:
        aired = _aired(episode)
        return parent.folder(f"Season {aired.year}" if aired else _SPECIALS, modified)
    return parent


def _collection_artwork(collection: Collection) -> list[tuple[str, Artwork]]:
    """The show's pictures, by the names media players look for: poster.jpg, fanart.jpg and clearlogo.png."""
    return [
        (f"{source.kind}.{source.forced_format or 'jpg'}", Artwork(source.url, source.forced_format or "jpg"))
        for source in collection_asset_sources(collection)
        if source.kind != "square"
    ]


def _episode_artwork(episode: Episode) -> Optional[Artwork]:
    picture = episode.thumbnail_landscape_path or episode.thumbnail_square_path or episode.thumbnail_portrait_path
    if not picture:
        return None
    if own_thumbnail_file(picture) is None and not picture.startswith(("https://", "http://")):
        return None
    return Artwork(picture)


def _add_episode_extra(
    folder: ShareFolder, profile: WebdavStreamProfile, episode: Episode, path: Path, modified: datetime,
    listed: dict[tuple[Optional[int], Optional[str]], tuple[ShareFolder, str]],
) -> None:
    """List an extra of an episode, such as its trailer: beside its episode, named after the episode's file with a
    suffix such as ``-trailer1`` as Plex reads an episode's extras, when the profile supports episode extras and
    the episode is listed; otherwise in the show's Trailers or Other folder, which most media players read."""
    info = episode.episode_identifier_info
    trailer = info.extra_type == EpisodeExtraType.TRAILER
    extension = _EXTENSIONS[profile.media_kinds[0]]
    episode_file = listed.get((info.season_number, info.episode_number)) if profile.episode_extras else None
    if episode_file is not None:
        parent, base = episode_file
        parent.add(ShareFile(
            f"{base}-{'trailer' if trailer else 'other'}{info.sub_episode_number}{extension}", modified, path=path,
        ))
        return
    folder.folder(_TRAILERS if trailer else _OTHER, modified).add(ShareFile(
        f"{'Trailer' if trailer else 'Extra'} {info.label} - {_name(episode.title)}{extension}", modified, path=path,
    ))


def show_folder(s: Session, profile: WebdavStreamProfile) -> ShareFolder:
    """The show's folder, with every downloaded episode and, as the profile chooses, its NFO files and artwork."""
    collection = profile.collection
    name = show_name(profile)
    metadata = WebdavMetadataFiles(profile.metadata_files)
    nfo = metadata is WebdavMetadataFiles.NFO_AND_ARTWORK
    artwork = metadata is not WebdavMetadataFiles.NONE
    changed = utc_datetime(collection.updated_at)
    folder = ShareFolder(name, changed)
    by_number = profile.season_folders == WebdavSeasonFolders.SEASON.value

    seasons: dict[Optional[int], ShareFolder] = {}
    # The folder and file name of each listed episode by its season and number, for the extras listed beside it.
    listed: dict[tuple[Optional[int], Optional[str]], tuple[ShareFolder, str]] = {}
    extras: list[tuple[Episode, Path, datetime]] = []
    for episode, download in get_stream_items(s, profile):
        if download is None or not (path := Path(download.file_path)).is_file():
            continue
        modified = _modified(path)
        extension = _EXTENSIONS[profile.media_kinds[0]]
        if episode.episode_type == EpIdType.TRAILER:
            # Plex and Jellyfin play the files in a show's Trailers folder as its trailers, by the name of the file.
            # The trailer's own number keeps the names apart and in order.
            folder.folder(_TRAILERS, modified).add(ShareFile(
                f"Trailer {episode.episode_number} - {_name(episode.title)}{extension}", modified, path=path,
            ))
            continue
        if episode.episode_type == EpIdType.EP_EXTRA:
            extras.append((episode, path, modified))
            continue
        episode_metadata = _episode_metadata(episode, by_number)
        parent = _season_folder(folder, profile, episode, episode_metadata, modified)
        if parent is not folder and nfo and by_number:
            # Specials have no season of their own: None stands for them.
            seasons.setdefault(None if episode_metadata.season_number == 0 else episode.season_id, parent)
        base = _episode_base_name(name, episode, episode_metadata, by_number)
        media = ShareFile(f"{base}{extension}", modified, path=path)
        parent.add(media)
        base = Path(media.name).stem
        if episode.episode_type == EpIdType.EP:
            info = episode.episode_identifier_info
            listed[(info.season_number, info.episode_number)] = (parent, base)
        if nfo:
            parent.add(ShareFile(
                f"{base}.nfo", utc_datetime(episode.updated_at),
                content=render_nfo(episode_metadata),
            ))
        if artwork and (picture := _episode_artwork(episode)) is not None:
            parent.add(ShareFile(f"{base}-thumb.jpg", utc_datetime(episode.updated_at), artwork=picture))

    for episode, path, modified in extras:
        _add_episode_extra(folder, profile, episode, path, modified, listed)

    if nfo:
        folder.add(ShareFile("tvshow.nfo", changed, content=render_nfo(build_show_metadata(collection))))
        episodes_seasons = {season.id: season for season in collection.seasons}
        for season_id, season_folder in seasons.items():
            season = _SPECIALS_SEASON if season_id is None else build_season_metadata(episodes_seasons[season_id])
            season_folder.add(ShareFile("season.nfo", changed, content=render_nfo(season)))
    if artwork:
        for file_name, picture in _collection_artwork(collection):
            folder.add(ShareFile(file_name, changed, artwork=picture))
    return folder


def shows_by_name(profiles: list[WebdavStreamProfile]) -> dict[str, WebdavStreamProfile]:
    """The shows of a share by their folder's name: their own, numbered where two are the same."""
    root = ShareFolder("", datetime.fromtimestamp(0, timezone.utc))
    named: dict[str, WebdavStreamProfile] = {}
    for profile in profiles:
        stub = ShareFolder(show_name(profile), utc_datetime(profile.collection.updated_at))
        root.add(stub)
        named[stub.name] = profile
    return named


def _named(names, name: str):
    """The one of ``names`` that is ``name``, matched as Windows does, without case."""
    return next((key for key in names if key.lower() == name.lower()), None)


def find(s: Session, profiles: list[WebdavStreamProfile], parts: list[str]) -> Optional[Union[ShareFolder, ShareFile]]:
    """The folder or file at ``parts`` in the share. Only the show it is in is looked through."""
    shows = shows_by_name(profiles)
    if not parts:
        root = ShareFolder("", datetime.fromtimestamp(0, timezone.utc))
        for name, profile in shows.items():
            root.add(ShareFolder(name, utc_datetime(profile.collection.updated_at)))
        return root
    show = _named(shows, parts[0])
    if show is None:
        return None
    node: Union[ShareFolder, ShareFile] = show_folder(s, shows[show])
    for part in parts[1:]:
        if not isinstance(node, ShareFolder) or (name := _named(node.children, part)) is None:
            return None
        node = node.children[name]
    return node
