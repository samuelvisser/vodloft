"""What a WebDAV stream profile's share holds: a folder per show, laid out the way media players read a TV show.

A show's folder holds its episodes, sorted into a folder per season, per year or none, each named
``<Show> - S01E05 - <Title>`` or ``<Show> - 2026-03-15 - <Title>``. An episode is listed only once VODLoft
has a whole file of it, downloaded or in the Stream Video Cache, as a player seeks in a file. Beside them,
as the profile chooses, are NFO files and artwork, made when they are asked for: nothing is written next
to the downloads.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from sqlalchemy.orm import Session

from backend.db.datetime_types import utc_datetime
from backend.db.models import Collection, Episode, EpisodeMediaDownload
from backend.db.models.stream_profile import WebdavStreamProfile
from backend.services.collection_assets import collection_asset_sources
from backend.services.download_metadata import build_episode_metadata, build_season_metadata, build_show_metadata
from backend.services.sites import collection_site
from backend.services.stream_episodes import get_stream_items
from backend.services.stream_tokens import profiles_for_token
from backend.services.thumbnails import own_thumbnail_file
from backend.services.video_cache import artwork_cache_path, episode_mp4_key, get_cached_mp4_path, mark_used
from backend.utils.collection_asset_files import download_collection_asset
from config import get_settings
from backend.types.stream_profile_types import WebdavMetadataFiles, WebdavSeasonFolders
from backend.utils.output_template import sanitize_path_component
from config.settings.submodels import FilenameRestrictionMode
from downloader.metadata import render_nfo

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


def _episode_file(
    profile: WebdavStreamProfile, episode: Episode, download: Optional[EpisodeMediaDownload],
) -> Optional[Path]:
    """The whole file the share lists for the episode: its download, or else its video in the Stream Video Cache."""
    if download is not None:
        return Path(download.file_path)
    if profile.media_kinds[0] != "mp4" or not profile.use_source_stream:
        return None
    site = collection_site(profile.collection)
    return get_cached_mp4_path(episode_mp4_key(site, profile.preferred_format, episode.uuid))


def _modified(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def _aired(episode: Episode) -> Optional[datetime]:
    moment = episode.published_date or episode.went_live_date
    return utc_datetime(moment) if moment is not None else None


def _episode_base_name(show: str, episode: Episode, by_number: bool) -> str:
    metadata = build_episode_metadata(episode, episode.collection)
    if by_number and metadata.season_number is not None and metadata.episode_number is not None:
        label = f"S{metadata.season_number:02d}E{metadata.episode_number:02d}"
    else:
        aired = _aired(episode)
        label = aired.strftime("%Y-%m-%d") if aired else f"E{episode.index:02d}"
    return f"{show} - {label} - {_name(episode.title)}"


def _season_folder(parent: ShareFolder, profile: WebdavStreamProfile, episode: Episode, modified: datetime) -> ShareFolder:
    layout = WebdavSeasonFolders(profile.season_folders)
    if layout is WebdavSeasonFolders.SEASON:
        return parent.folder(f"Season {episode.season.season_number:02d}", modified)
    if layout is WebdavSeasonFolders.YEAR:
        aired = _aired(episode)
        return parent.folder(f"Season {aired.year}" if aired else "Specials", modified)
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


def show_folder(s: Session, profile: WebdavStreamProfile) -> ShareFolder:
    """The show's folder, with every episode VODLoft has a whole file of and, as the profile chooses, its
    NFO files and artwork."""
    collection = profile.collection
    name = show_name(profile)
    metadata = WebdavMetadataFiles(profile.metadata_files)
    nfo = metadata is WebdavMetadataFiles.NFO_AND_ARTWORK
    artwork = metadata is not WebdavMetadataFiles.NONE
    changed = utc_datetime(collection.updated_at)
    folder = ShareFolder(name, changed)
    by_number = profile.season_folders == WebdavSeasonFolders.SEASON.value

    seasons: dict[int, ShareFolder] = {}
    for episode, download in get_stream_items(s, profile):
        path = _episode_file(profile, episode, download)
        if path is None or not path.is_file():
            continue
        modified = _modified(path)
        parent = _season_folder(folder, profile, episode, modified)
        if parent is not folder and nfo and by_number:
            seasons.setdefault(episode.season_id, parent)
        base = _episode_base_name(name, episode, by_number)
        media = ShareFile(f"{base}{_EXTENSIONS[profile.media_kinds[0]]}", modified, path=path)
        parent.add(media)
        base = Path(media.name).stem
        if nfo:
            parent.add(ShareFile(
                f"{base}.nfo", utc_datetime(episode.updated_at),
                content=render_nfo(build_episode_metadata(episode, collection)),
            ))
        if artwork and (picture := _episode_artwork(episode)) is not None:
            parent.add(ShareFile(f"{base}-thumb.jpg", utc_datetime(episode.updated_at), artwork=picture))

    if nfo:
        folder.add(ShareFile("tvshow.nfo", changed, content=render_nfo(build_show_metadata(collection))))
        episodes_seasons = {season.id: season for season in collection.seasons}
        for season_id, season_folder in seasons.items():
            season_folder.add(ShareFile(
                "season.nfo", changed, content=render_nfo(build_season_metadata(episodes_seasons[season_id])),
            ))
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
