"""Music: Music collections and profiles, the tags of a track, and its square cover art."""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.services.errors import ServiceError
from backend.types.collection_types import CollectionType
from backend.types.local_media_profile_types import CollectionLocalMediaProfileScope


def _new_session() -> Session:
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


MUSIC = {"name": "Music", "output_template": "/downloads/music/{{ artist }}/{{ album }}/{{ track_number_padded }} - {{ title }}.ext"}


def test_a_profile_for_music_tracks_keeps_audio_and_one_for_music_videos_video():
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate
    from backend.services.local_media_profile_changes import create_collection_local_media_profile

    tracks = CollectionLocalMediaProfileAPICreate(
        collection_scope="music_tracks", preferred_format="format_audio_only", audio_format="flac", **MUSIC,
    )
    with pytest.raises(ValidationError, match="A profile for Music tracks downloads audio only"):
        CollectionLocalMediaProfileAPICreate(collection_scope="music_tracks", preferred_format="format_1080p", **MUSIC)
    # FLAC is for Music tracks.
    with pytest.raises(ValidationError, match="FLAC is for profiles for Music tracks"):
        CollectionLocalMediaProfileAPICreate(preferred_format="format_audio_only", audio_format="flac", **MUSIC)
    # A profile for Music videos calls each one a music video.
    videos = CollectionLocalMediaProfileAPICreate(preferred_format="format_1080p", collection_scope="music_videos", **MUSIC)
    assert (videos.collection_scope, videos.episode_nfo) == (CollectionLocalMediaProfileScope.MUSIC_VIDEOS, "music_video")

    session = _new_session()
    profile = create_collection_local_media_profile(session, tracks)
    assert (type(profile).__name__, profile.type, profile.collection_scope) == (
        "CollectionLocalMediaProfile", "collection", "music_tracks",
    )


def test_a_profile_with_downloads_does_not_switch_to_or_from_music_tracks():
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPIUpdate
    from backend.services.local_media_profile_changes import _refuse_tracks_switch_with_downloads

    def change(saved, wanted, downloads=True):
        session = SimpleNamespace(scalar=lambda _statement: 1 if downloads else None)
        fields = CollectionLocalMediaProfileAPIUpdate(
            collection_scope=wanted, preferred_format="format_audio_only", **MUSIC,
        )
        _refuse_tracks_switch_with_downloads(session, SimpleNamespace(id=1, collection_scope=saved), fields)

    change("both", "music_videos")
    change("music_videos", "music_tracks", downloads=False)
    with pytest.raises(ServiceError, match="already has downloads, so it can't be changed to Music tracks") as refused:
        change("music_videos", "music_tracks")
    assert refused.value.field == "collectionScope"
    with pytest.raises(ServiceError, match="already has downloaded music tracks"):
        change("music_tracks", "podcast")


def test_a_profile_for_podcasts_and_series_is_not_offered_for_music():
    assert CollectionLocalMediaProfileScope.BOTH.collection_types() == ("podcast", "series")
    assert CollectionLocalMediaProfileScope.MUSIC_TRACKS.collection_types() == ("music",)
    assert CollectionLocalMediaProfileScope.MUSIC_VIDEOS.collection_types() == ("music",)
    assert CollectionType.MUSIC.by_season and CollectionType.SERIES.by_season and not CollectionType.PODCAST.by_season


def test_a_collection_becomes_music_only_when_its_download_profiles_suit_it():
    from backend.api.endpoints.collections.service import _check_profiles_suit_type

    def collection(*scopes):
        return SimpleNamespace(title="Synthwave", download_profiles=[
            SimpleNamespace(local_media_profile=SimpleNamespace(name=f"Profile {scope}", collection_scope=scope)) for scope in scopes
        ])

    _check_profiles_suit_type(collection("music_tracks", "music_videos"), CollectionType.MUSIC)
    _check_profiles_suit_type(collection("both", "series"), CollectionType.SERIES)
    with pytest.raises(ServiceError, match="Profile both, which is not offered for music collections") as refused:
        _check_profiles_suit_type(collection("both"), CollectionType.MUSIC)
    assert refused.value.field == "type"


def test_a_track_is_tagged_with_its_album_artist_and_number():
    from downloader.metadata import MediaServerMetadata

    tags = MediaServerMetadata(
        kind="track", title="Nightcall", collection_title="Kavinsky", season_number=2, album="OutRun", track_number=3,
        authors=("Kavinsky",),
    ).ffmpeg_tags()

    assert (tags["album"], tags["track"], tags["artist"], tags["album_artist"]) == ("OutRun", "3", "Kavinsky", "Kavinsky")
    # Music players group by album: the show and season tags of an episode would split it up.
    assert "show" not in tags and "season_number" not in tags


def _episode(season_name, season_number, slug=None):
    collection = SimpleNamespace(title="Kavinsky Videos", author_name="Kavinsky", channel=SimpleNamespace(title="Kavinsky"))
    return SimpleNamespace(
        collection=collection, season=SimpleNamespace(name=season_name, season_number=season_number, slug=slug or season_name.lower()),
    )


def test_the_album_of_a_track_is_its_named_season_and_else_the_collection():
    from backend.utils.music import _album, collection_artist

    assert _album(_episode("OutRun", 3)) == "OutRun"
    assert _album(_episode("Reborn", 4)) == "Reborn"
    # A season per year holds a feed's uploads, not an album, unless the user named it, and stays one when renumbered.
    assert _album(_episode("2024", 2024)) == "Kavinsky Videos"
    assert _album(_episode("2024", 3)) == "Kavinsky Videos"
    assert _album(_episode("Summer tour", 3, slug="2024")) == "Summer tour"
    assert _album(_episode("Specials", 0)) == "Kavinsky Videos"
    assert collection_artist(_episode("Reborn", 4).collection) == "Kavinsky"


def test_a_flac_track_gets_its_tags_and_a_square_cover(tmp_path):
    from downloader.ffmpeg import embed_media

    track, cover = tmp_path / "03 - Nightcall.flac", tmp_path / "cover.jpg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", str(track)], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=red:size=320x180", "-frames:v", "1", str(cover)], check=True)

    embed_media(str(track), metadata={"title": "Nightcall", "album": "OutRun", "track": "3"}, thumbnail_path=str(cover),
                audio_only=True, square_artwork=True)

    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(track)], check=True, capture_output=True,
    ).stdout)
    picture = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    assert (picture["width"], picture["height"]) == (180, 180)
    tags = {key.lower(): value for key, value in probe["format"]["tags"].items()}
    assert (tags["album"], tags["track"]) == ("OutRun", "3")


def test_a_collection_without_download_profiles_can_become_music():
    from backend.api.endpoints.collections.service import update_collection
    from backend.api.models.collection import CollectionAPIUpdate
    from backend.db.models import Collection

    session = _new_session()
    session.add(Collection(
        uuid="uuid-synth", slug="synth", source_key="ytdlp", title="Synthwave", sharing_url="https://tube.example/synth",
        membership_level="FREE", type="series", episode_identifier="seasonal", author_name="x", author_slug="x",
    ))
    session.flush()

    update_collection(session, "synth", CollectionAPIUpdate.model_validate({
        "type": "music", "title": "Synthwave", "sharingUrl": "https://tube.example/synth", "authorName": "x",
    }))
    assert session.get(Collection, 1).type == "music"
