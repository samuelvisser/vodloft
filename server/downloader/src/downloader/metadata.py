from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class MediaServerMetadata:
    kind: str
    title: str
    description: str | None = None
    unique_id: str | None = None
    # Which service ``unique_id`` belongs to, as media servers read it. Set with ``unique_id``.
    unique_id_type: str | None = None
    source_url: str | None = None
    collection_title: str | None = None
    season_number: int | None = None
    episode_index: int | None = None
    episode_number: int | None = None
    aired: date | None = None
    release_date: date | None = None
    duration_seconds: float | None = None
    authors: tuple[str, ...] = field(default_factory=tuple)
    genres: tuple[str, ...] = field(default_factory=tuple)
    directors: tuple[str, ...] = field(default_factory=tuple)
    writers: tuple[str, ...] = field(default_factory=tuple)
    cast: tuple[str, ...] = field(default_factory=tuple)
    studios: tuple[str, ...] = field(default_factory=tuple)
    language: str | None = None
    country: str | None = None
    content_rating: str | None = None
    parent_movie_title: str | None = None
    media_type: str | None = None
    album: str | None = None
    """For a track: the album it is on, which music players group by."""
    track_number: int | None = None
    track_count: int | None = None
    """How many tracks the album has; the track tag reads like 3/10 with it."""

    @property
    def is_track(self) -> bool:
        return self.kind == "track"

    @property
    def is_music_video(self) -> bool:
        return self.kind == "musicvideo"

    def cleared_ffmpeg_tags(self) -> tuple[str, ...]:
        """The tags VODLoft writes that this metadata has no value for, so rewriting a file's tags clears them
        instead of leaving an old value behind, such as an episode number once a collection numbers by date."""
        tags = self.ffmpeg_tags()
        return tuple(key for key in REWRITTEN_FFMPEG_TAGS if key not in tags)

    def ffmpeg_tags(self) -> dict[str, str]:
        tags: dict[str, str] = {"title": self.title}
        if self.description:
            tags["description"] = self.description
            tags["comment"] = self.description
        if self.is_track:
            # Music players group by album and album artist, and sort by track number.
            if self.album:
                tags["album"] = self.album
            if self.track_number is not None:
                total = f"/{self.track_count}" if self.track_count and self.track_count >= self.track_number else ""
                tags["track"] = f"{self.track_number}{total}"
        elif self.collection_title:
            tags["show"] = self.collection_title
            tags["album"] = self.collection_title
        if self.authors:
            joined = ", ".join(self.authors)
            tags["artist"] = joined
            tags["album_artist"] = joined
        if self.aired:
            tags["date"] = self.aired.isoformat()
        elif self.release_date:
            tags["date"] = self.release_date.isoformat()
        if self.season_number is not None and not self.is_track:
            tags["season_number"] = str(self.season_number)
        if self.episode_number is not None:
            tags["episode_id"] = str(self.episode_number)
        if self.episode_index is not None:
            tags["episode_sort"] = str(self.episode_index)
        if self.genres:
            tags["genre"] = ", ".join(self.genres)
        if self.directors:
            tags["director"] = ", ".join(self.directors)
        if self.writers:
            tags["writer"] = ", ".join(self.writers)
        if self.cast:
            tags["actor"] = ", ".join(self.cast)
        if self.studios:
            tags["publisher"] = ", ".join(self.studios)
        if self.language:
            tags["language"] = self.language
        if self.country:
            tags["country"] = self.country
        if self.content_rating:
            tags["rating"] = self.content_rating
        if self.source_url:
            tags["purl"] = self.source_url
        if self.unique_id and self.unique_id_type:
            tags[f"{self.unique_id_type}_id"] = self.unique_id
        if self.media_type:
            tags["media_type"] = self.media_type
        return tags


# Every tag ffmpeg_tags writes, apart from the Source's own id, whose name depends on the Source.
REWRITTEN_FFMPEG_TAGS = (
    "title", "description", "comment", "album", "track", "show", "artist", "album_artist", "date", "season_number",
    "episode_id", "episode_sort", "genre", "director", "writer", "actor", "publisher", "language", "country",
    "rating", "purl", "media_type",
)


def write_nfo(media_path: str, metadata: MediaServerMetadata) -> str:
    destination = Path(media_path).with_suffix(".nfo")
    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = Path(str(destination) + ".part")
    placeholder_fd: int | None = None
    placeholder_created = False
    try:
        placeholder_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o666,
        )
        placeholder_created = True
        os.close(placeholder_fd)
        placeholder_fd = None
        ET.ElementTree(_nfo_root(metadata)).write(
            part_path,
            encoding="utf-8",
            xml_declaration=True,
        )
        os.replace(part_path, destination)
        return str(destination)
    except BaseException:
        if placeholder_fd is not None:
            os.close(placeholder_fd)
        part_path.unlink(missing_ok=True)
        if placeholder_created:
            destination.unlink(missing_ok=True)
        raise


# The root element of each kind of NFO file; movies, their extras and videos are all a "movie".
_NFO_ROOTS = {"episode": "episodedetails", "tvshow": "tvshow", "season": "season", "musicvideo": "musicvideo"}


def _nfo_root(metadata: MediaServerMetadata) -> ET.Element:
    root = ET.Element(_NFO_ROOTS.get(metadata.kind, "movie"))
    _text(root, "title", metadata.title)
    _text(root, "plot", metadata.description)
    if metadata.unique_id and metadata.unique_id_type:
        unique = ET.SubElement(root, "uniqueid", {"type": metadata.unique_id_type, "default": "true"})
        unique.text = metadata.unique_id
    _text(root, "showtitle", metadata.collection_title)
    _text(root, "seasonnumber" if metadata.kind == "season" else "season", metadata.season_number)
    _text(root, "episode", metadata.episode_number)
    _text(root, "aired", metadata.aired)
    _text(root, "premiered", metadata.release_date)
    if metadata.release_date:
        _text(root, "year", metadata.release_date.year)
    elif metadata.is_music_video and metadata.aired:
        _text(root, "year", metadata.aired.year)
    if metadata.duration_seconds and metadata.duration_seconds > 0:
        _text(root, "runtime", max(1, round(metadata.duration_seconds / 60)))
    _text(root, "mpaa", metadata.content_rating)
    _text(root, "country", metadata.country)
    _text(root, "language", metadata.language)
    _text(root, "parenttitle", metadata.parent_movie_title)
    _text(root, "mediatype", metadata.media_type)
    _text(root, "source", metadata.source_url)

    for value in metadata.genres:
        _text(root, "genre", value)
    for value in metadata.directors:
        _text(root, "director", value)
    for value in metadata.writers:
        _text(root, "credits", value)
    for value in metadata.studios:
        _text(root, "studio", value)
    for value in metadata.authors:
        # A music video's artist is who media servers file it under.
        _text(root, "artist" if metadata.is_music_video else "credits", value)
    for value in metadata.cast:
        actor = ET.SubElement(root, "actor")
        _text(actor, "name", value)
    return root


def _text(parent: ET.Element, name: str, value) -> None:
    if value is None or value == "":
        return
    element = ET.SubElement(parent, name)
    element.text = str(value)


def render_nfo(metadata: MediaServerMetadata, *, kodi_safe: bool = False) -> bytes:
    """Generate the exact sidecar payload before filesystem work is planned.

    ``kodi_safe`` replaces what Kodi's fonts cannot show, such as emoji, so Kodi does not show empty boxes
    or cut the text short.
    """
    root = _nfo_root(metadata)
    if kodi_safe:
        for element in root.iter():
            if element.text:
                element.text = _kodi_safe_text(element.text)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# The joiners and variation selectors that build an emoji out of others, and the tags of flag emoji.
_EMOJI_JOINERS = re.compile("[\u200d\ufe0e\ufe0f\U000e0020-\U000e007f]")
# Emoji and other characters outside the Basic Multilingual Plane, and the symbol blocks emoji live in.
_KODI_UNREADABLE = re.compile("[\U00010000-\U0010ffff\u2600-\u27bf\u2b00-\u2bff]+")


def _kodi_safe_text(text: str) -> str:
    """Replace each run of emoji with one □, which Kodi can show."""
    return _KODI_UNREADABLE.sub("\u25a1", _EMOJI_JOINERS.sub("", text))
