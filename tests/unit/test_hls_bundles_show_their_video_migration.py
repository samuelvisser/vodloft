"""HLS downloads VODLoft split itself before their parts left out the edit list lose the edit lists
that begin with an empty edit, with which Apple's players show no picture."""
from __future__ import annotations

import asyncio
import importlib
import shutil
import subprocess

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import available_artifact, use_database

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

MIGRATION = "backend.db.background_migrations.versions.a1af462faa04_hls_bundles_show_their_video"


class _Context:
    def raise_if_canceled(self):
        return None

    def update_progress(self, current, total, message=None):
        return None


@pytest.fixture
def factory():
    import backend.api.endpoints.collections.router  # noqa: F401  (loads every model first)
    from backend.db import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    use_database(engine)
    yield sessionmaker(engine)
    engine.dispose()


def _split(source, directory):
    """Split a track into HLS parts as VODLoft did before: ffmpeg then kept an edit list."""
    directory.mkdir()
    subprocess.run([
        "ffmpeg", "-loglevel", "error", "-y", "-i", str(source), "-map", "0", "-c", "copy",
        "-f", "hls", "-hls_time", "2", "-hls_playlist_type", "vod", "-hls_segment_type", "fmp4",
        "-hls_flags", "single_file", "-hls_segment_filename", str(directory / "media.mp4"), str(directory / "playlist.m3u8"),
    ], check=True)


def _bundle(tmp_path):
    """A downloaded YouTube video with 360p and its audio, as the files YouTube has: a video whose
    first frame does not start at 0."""
    master = tmp_path / "episode.m3u8"
    assets = tmp_path / "episode.m3u8.assets"
    assets.mkdir()
    (assets / ".vodloft-hls-bundle").write_text("VODLoft local HLS bundle\n")
    video, audio = tmp_path / "video.mp4", tmp_path / "audio.m4a"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25", "-t", "6",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-g", "25", "-an", str(video)], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "6",
                    "-c:a", "aac", str(audio)], check=True)
    _split(video, assets / "360p")
    _split(audio, assets / "audio-0")
    master.write_text(
        "#EXTM3U\n#EXT-X-VERSION:7\n"
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,URI="hls/audio-0/playlist.m3u8"\n'
        '#EXT-X-STREAM-INF:BANDWIDTH=500000,RESOLUTION=640x360,AUDIO="audio"\nhls/360p/playlist.m3u8\n'
    )
    return master


def _download(session, master):
    from backend.db.models import Collection, Episode, LocalMediaProfile, Season
    from backend.db.models.media_download import EpisodeMediaDownload

    local = LocalMediaProfile(slug="hls", name="HLS", preferred_format="format_hls", output_template="/x/{{ episode }}.ext")
    collection = Collection(
        source_key="ytdlp", uuid="channel", slug="channel", title="Channel", description=None,
        sharing_url="https://www.youtube.com/@channel", membership_level="FREE", type="series",
        episode_identifier="numbered", author_name="A", author_slug="a",
    )
    season = Season(collection=collection, index=1, slug="channel-1", name="One")
    episode = Episode(
        source_key="ytdlp", uuid="video", type="episode", collection=collection, season=season, index=1,
        episode_identifier="ep.1", slug="video", title="Video", publish_status="published_final",
        sharing_url="https://www.youtube.com/watch?v=video",
    )
    session.add_all([local, collection, season, episode])
    session.flush()
    session.add(EpisodeMediaDownload(
        type="episode", media_item_id=episode.id, local_media_profile_id=local.id, file_path=str(master),
        **available_artifact(),
    ))
    session.commit()


def _header(playlist):
    byte_range = playlist.read_text().split('BYTERANGE="', 1)[1].split('"', 1)[0]
    length, offset = (int(value) for value in byte_range.split("@"))
    with (playlist.parent / "media.mp4").open("rb") as media:
        media.seek(offset)
        return media.read(length)


def test_hls_downloads_lose_edit_lists_that_begin_empty(factory, monkeypatch, tmp_path):
    module = importlib.import_module(MIGRATION)
    monkeypatch.setattr(module, "get_session", factory)
    master = _bundle(tmp_path)
    video, audio = (tmp_path / "episode.m3u8.assets" / name / "playlist.m3u8" for name in ("360p", "audio-0"))
    assert module._empty_edits(_header(video), 0, len(_header(video)))
    sizes = {path: path.stat().st_size for path in (tmp_path / "episode.m3u8.assets").rglob("*")}
    audio_header = _header(audio)
    with factory() as session:
        _download(session, master)

    asyncio.run(module.migrate(_Context()))

    # Only the box's name changed: every part stays where its playlist says, and the video still plays.
    assert b"edts" not in _header(video) and b"free" in _header(video)
    assert sizes == {path: path.stat().st_size for path in (tmp_path / "episode.m3u8.assets").rglob("*")}
    assert _header(audio) == audio_header  # The audio's edit list does not begin empty.
    probe = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-f", "null", "-"], capture_output=True, text=True)
    assert probe.returncode == 0, probe.stderr

    # Running it again changes nothing.
    header = _header(video)
    asyncio.run(module.migrate(_Context()))
    assert _header(video) == header
