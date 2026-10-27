"""The yt-dlp Source: looking up links, downloading through yt-dlp, updates and cookies."""
from __future__ import annotations

import hashlib
import sys
import textwrap
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.errors import source_request_error_handler
from backend.services.source_requests import SourceRequestError
from downloader.errors import DownloadError, EncryptedMediaError, MediaUnavailableError
from sources import Feature, LinkKind, PlaybackKind, ProgramStatus, Source, registry
from sources import ytdlp_runner as runner
from sources.ytdlp import GENERIC_SITE, YtDlpSource


YOUTUBE_VIDEO = {
    "_type": "video", "id": "dQw4w9WgXcQ", "extractor_key": "Youtube",
    "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "A video",
    "description": "About it", "duration": 212, "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
    "uploader": "A Channel", "uploader_url": "https://www.youtube.com/@a-channel", "upload_date": "20091025",
}


@pytest.fixture
def ytdlp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ytdlp_directory", lambda: tmp_path / "yt-dlp")
    return tmp_path / "yt-dlp"


@pytest.fixture
def lookups(monkeypatch):
    """Answer yt-dlp lookups from a dict of link → info."""
    answers: dict[str, dict] = {}
    calls: list[tuple[str, ...]] = []

    def run_json(*args):
        calls.append(args)
        url = args[-1]
        if url not in answers:
            raise runner.YtDlpError(f"Unsupported URL: {url}")
        return answers[url]

    monkeypatch.setattr(runner, "run_json", run_json)
    return answers, calls


def test_a_youtube_video_resolves_to_a_video_named_by_its_id(lookups):
    answers, calls = lookups
    answers["https://youtu.be/dQw4w9WgXcQ"] = YOUTUBE_VIDEO
    source = YtDlpSource()

    link = source.resolve("https://youtu.be/dQw4w9WgXcQ")
    assert (link.kind, link.slug, link.site, link.author_name) == (LinkKind.VIDEO, "dQw4w9WgXcQ", "YouTube", "A Channel")
    assert link.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    details = source.video_details("https://youtu.be/dQw4w9WgXcQ")
    assert details.published_at == datetime(2009, 10, 25, tzinfo=timezone.utc)
    assert details.duration == 212.0
    assert details.author_url == "https://www.youtube.com/@a-channel"
    # Adding the video right after looking it up reuses the lookup.
    assert len(calls) == 1
    assert "--no-playlist" in calls[0]


def test_other_sites_are_prefixed_and_unknown_pages_are_best_effort(lookups):
    answers, _ = lookups
    answers["https://vimeo.com/1"] = {"id": "1", "extractor_key": "Vimeo", "webpage_url_domain": "vimeo.com", "title": "V", "timestamp": 0}
    answers["https://example.com/clip.mp4"] = {"id": "clip", "extractor_key": "Generic", "title": "clip"}
    source = YtDlpSource()

    vimeo = source.resolve("https://vimeo.com/1")
    assert (vimeo.slug, vimeo.site) == ("vimeo-1", "vimeo.com")
    assert source.video_details("https://vimeo.com/1").published_at == datetime(1970, 1, 1, tzinfo=timezone.utc)
    generic = source.resolve("https://example.com/clip.mp4")
    assert (generic.slug, generic.site) == ("generic-clip", GENERIC_SITE)
    # A page yt-dlp cannot use is not recognised, so the link gets the usual message.
    assert source.resolve("https://example.com/about") is None


def test_playlists_resolve_to_shows_but_are_not_videos(lookups):
    answers, _ = lookups
    answers["https://www.youtube.com/playlist?list=PL1"] = {
        "_type": "playlist", "id": "PL1", "extractor_key": "YoutubeTab", "title": "A playlist", "uploader": "A Channel",
    }
    source = YtDlpSource()
    link = source.resolve("https://www.youtube.com/playlist?list=PL1")
    assert (link.kind, link.slug, link.title) == (LinkKind.SHOW, "PL1", "A playlist")
    with pytest.raises(runner.YtDlpError, match="not a single video"):
        source.video_details("https://www.youtube.com/playlist?list=PL1")


def test_playback_hands_the_page_to_ytdlp_with_the_cookies_file(ytdlp_dir):
    source = YtDlpSource()
    playback = source.video_playback(slug="x", url="https://www.youtube.com/watch?v=x")
    assert playback.kind is PlaybackKind.YTDLP
    assert playback.url == "https://www.youtube.com/watch?v=x"
    assert "--cookies" not in playback.command

    source.save_cookies(b"# Netscape HTTP Cookie File\n#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n")
    assert source.has_cookies()
    command = source.video_playback(slug="x", url="https://x").command
    assert command[command.index("--cookies") + 1] == str(ytdlp_dir / "cookies.txt")

    source.remove_cookies()
    assert not source.has_cookies()
    with pytest.raises(ValueError, match="Netscape"):
        source.save_cookies(b"not cookies")


class _Release:
    """The two files yt-dlp publishes with a release: its program and their checksums."""

    def __init__(self, program: bytes, *, checksum_of: bytes | None = None):
        self.program = program
        self.checksum = hashlib.sha256(program if checksum_of is None else checksum_of).hexdigest()

    def get(self, url, **_kwargs):
        release = self

        class Response:
            text = f"{release.checksum}  yt-dlp\n{'0' * 64}  yt-dlp.exe\n"

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def raise_for_status(self):
                pass

            def iter_content(self, _size):
                yield release.program

        assert url in (runner.RELEASE_URL, runner.CHECKSUMS_URL)
        return Response()


def test_the_updated_release_replaces_the_shipped_ytdlp(ytdlp_dir, monkeypatch):
    assert runner.program()[1:] == ("-m", "yt_dlp")
    assert runner.update_due()

    monkeypatch.setattr(runner.requests, "get", _Release(b"release").get)
    monkeypatch.setattr(runner, "version", lambda prog=None: "2026.10.21")
    status = YtDlpSource().update_program()

    assert (ytdlp_dir / "yt-dlp").read_bytes() == b"release"
    assert runner.program() == (sys.executable, str(ytdlp_dir / "yt-dlp"))
    assert status.version == "2026.10.21"
    assert status.last_update_at is not None and status.last_update_error is None
    assert not runner.update_due()
    assert runner.update_due(datetime.now(timezone.utc) + timedelta(days=8))


def test_a_release_that_does_not_match_its_checksum_is_not_used(ytdlp_dir, monkeypatch):
    monkeypatch.setattr(runner.requests, "get", _Release(b"tampered", checksum_of=b"release").get)
    monkeypatch.setattr(runner, "version", lambda prog=None: "2026.10.21")

    with pytest.raises(runner.YtDlpError, match="checksum"):
        runner.update()

    assert not (ytdlp_dir / "yt-dlp").exists()
    assert list(ytdlp_dir.glob(".yt-dlp-*")) == []
    assert runner.last_update()[1] == "The downloaded yt-dlp release does not match its published checksum"


def test_a_failed_update_keeps_the_current_ytdlp_and_says_why(ytdlp_dir, monkeypatch):
    def offline(*_args, **_kwargs):
        raise OSError("the network is down")

    monkeypatch.setattr(runner.requests, "get", offline)
    with pytest.raises(OSError):
        runner.update()
    assert not (ytdlp_dir / "yt-dlp").exists()
    assert list(ytdlp_dir.glob(".yt-dlp-*")) == []
    assert runner.last_update() == (None, "the network is down")


def test_profile_formats_map_to_ytdlp_options():
    from downloader.ytdlp import resolve_ytdlp_source, ytdlp_format_options

    video = ytdlp_format_options("format_720p", audio_only=False)
    assert video[video.index("-S") + 1].startswith("res:720,")
    assert "--merge-output-format" in video
    audio = ytdlp_format_options("format_audio_only", audio_only=True)
    assert audio[audio.index("--audio-format") + 1] == "m4a"

    source = resolve_ytdlp_source("https://x", command=("yt-dlp",), preferred_format="format_4k", audio_only=False)
    assert (source.extension, source.ytdlp_command[0], source.use_hls) == ("mp4", "yt-dlp", False)
    assert resolve_ytdlp_source("https://x", command=("yt-dlp",), preferred_format="format_audio_only", audio_only=True).extension == "m4a"
    with pytest.raises(DownloadError, match="HLS"):
        resolve_ytdlp_source("https://x", command=("yt-dlp",), preferred_format="format_hls", audio_only=False)


FAKE_YTDLP = textwrap.dedent('''
    import pathlib, sys
    args = sys.argv[1:]
    url = args[-1]
    if "drm" in url:
        print("ERROR: [site] 1: This video is DRM protected")
        sys.exit(1)
    if "gone" in url:
        print("ERROR: [youtube] x: Video unavailable")
        sys.exit(1)
    work = pathlib.Path(args[args.index("-P") + 1])
    template = args[args.index("--progress-template") + 1].removeprefix("download:")
    for done in (10, 50, 100):
        print(template.replace("%(progress.downloaded_bytes)s", str(done)).replace("%(progress.total_bytes)s", "100").replace("%(progress.total_bytes_estimate)s", "NA"))
    for done in (5, 20):
        print(template.replace("%(progress.downloaded_bytes)s", str(done)).replace("%(progress.total_bytes)s", "20").replace("%(progress.total_bytes_estimate)s", "NA"))
    print("[Merger] Merging formats")
    (work / "media.mp4").write_bytes(b"x" * 120)
    print("[vodloft-file] " + str(work / "media.mp4"))
''')


@pytest.fixture
def fake_ytdlp(tmp_path):
    script = tmp_path / "fake_ytdlp.py"
    script.write_text(FAKE_YTDLP)
    return (sys.executable, str(script))


def test_ytdlp_downloads_report_progress_across_streams(fake_ytdlp, tmp_path):
    from downloader.ytdlp import download_ytdlp

    seen = []
    result = download_ytdlp("https://x/video", str(tmp_path / "out.mp4"), command=fake_ytdlp, progress=seen.append)
    assert (tmp_path / "out.mp4").read_bytes() == b"x" * 120
    assert result.bytes_downloaded == 120
    assert [p.bytes_downloaded for p in seen] == [10, 50, 100, 105, 120, 120]
    assert seen[3].total_bytes == 120
    assert not (tmp_path / "out.mp4.ytdlp").exists()


def test_ytdlp_errors_say_what_went_wrong(fake_ytdlp, tmp_path):
    from downloader.ytdlp import download_ytdlp

    with pytest.raises(EncryptedMediaError, match="protected by DRM"):
        download_ytdlp("https://x/drm", str(tmp_path / "a.mp4"), command=fake_ytdlp)
    with pytest.raises(MediaUnavailableError, match="Video unavailable"):
        download_ytdlp("https://x/gone", str(tmp_path / "b.mp4"), command=fake_ytdlp)
    assert list(tmp_path.glob("*.mp4*")) == []


def test_a_cancelled_ytdlp_download_stops_it(fake_ytdlp, tmp_path):
    from downloader.errors import DownloadCancelled
    from downloader.ytdlp import download_ytdlp

    with pytest.raises(DownloadCancelled):
        download_ytdlp("https://x/video", str(tmp_path / "c.mp4"), command=fake_ytdlp, should_cancel=lambda: True)
    assert list(tmp_path.glob("c.mp4*")) == []


class ToolSource(Source):
    id = "tool"
    name = "Tool"
    domains = ("tool.example",)
    features = frozenset({Feature.PROGRAM_UPDATES, Feature.COOKIES})

    def __init__(self, *, due=True, fails=False):
        self.due, self.fails, self.updates, self.cookies = due, fails, 0, None

    def resolve(self, url):
        return None

    def episode_media(self, **_kwargs):
        raise NotImplementedError

    def movie_playback(self, **_kwargs):
        raise NotImplementedError

    def program_status(self):
        return ProgramStatus(name="tool", version=f"v{self.updates}")

    def program_update_due(self):
        return self.due

    def update_program(self):
        if self.fails:
            raise RuntimeError("release server said no")
        self.updates += 1
        return self.program_status()

    def has_cookies(self):
        return self.cookies is not None

    def save_cookies(self, content):
        if b"\t" not in content:
            raise ValueError("Not a cookies file")
        self.cookies = content

    def remove_cookies(self):
        self.cookies = None


@pytest.fixture
def tool_sources(monkeypatch):
    monkeypatch.setattr(registry, "_sources", {})
    return registry.register(ToolSource()), registry.register(type("Plain", (ToolSource,), {
        "id": "plain", "name": "Plain", "features": frozenset(),
    })())


@pytest.fixture
def client(tool_sources, monkeypatch):
    from backend.api.endpoints.sources import router as source_router_module

    @contextmanager
    def db_session():
        yield None

    monkeypatch.setattr(source_router_module, "db_session", db_session)
    app = FastAPI()
    app.include_router(source_router_module.router, prefix="/api")
    app.add_exception_handler(SourceRequestError, source_request_error_handler)
    with TestClient(app) as test_client:
        yield test_client


def test_the_program_and_cookies_endpoints(client, tool_sources):
    tool, _ = tool_sources
    assert client.get("/api/sources/tool/program").json()["version"] == "v0"
    assert client.post("/api/sources/tool/program/update").json()["version"] == "v1"
    tool.fails = True
    failed = client.post("/api/sources/tool/program/update")
    assert failed.status_code == 502
    assert "release server said no" in failed.json()["detail"]

    assert client.get("/api/sources/tool/cookies").json() == {"hasCookies": False, "status": None}
    assert client.put("/api/sources/tool/cookies", json={"content": "a\tb"}).json() == {"hasCookies": True, "status": None}
    assert client.put("/api/sources/tool/cookies", json={"content": "nope"}).status_code == 422
    assert client.delete("/api/sources/tool/cookies").json() == {"hasCookies": False, "status": None}

    assert client.get("/api/sources/plain/program").status_code == 404
    assert client.put("/api/sources/plain/cookies", json={"content": "a\tb"}).status_code == 404
    assert client.get("/api/sources/nope/cookies").status_code == 404


def test_the_weekly_update_only_updates_sources_that_are_due(tool_sources):
    from task_manager.tasks.workers.update_source_programs.service import run_update_source_programs

    tool, _ = tool_sources
    assert run_update_source_programs().summary == "Updated tool v1"
    tool.due = False
    assert run_update_source_programs().summary == "Everything is up to date"
    tool.due, tool.fails = True, True
    with pytest.raises(RuntimeError, match="Could not update Tool"):
        run_update_source_programs()
