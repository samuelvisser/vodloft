"""A collection that splits videos by chapter: each part is an episode of its own, downloaded as its stretch of the
video, while the Source is only ever asked about the whole video."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from sources import Chapter, Feature, ItemRefresh, VideoDetails
from test_ytdlp_collections import ListedSource, _video, session  # noqa: F401

ALBUMS = "https://www.youtube.com/playlist?list=PLalbums"
CHAPTERS = (Chapter("Intro", 0.0, 95.5), Chapter("Rain", 95.5, 260.0), Chapter("Outro", 260.0, 300.0))


class ChaptersSource(ListedSource):
    """Lists its videos without their chapters, which only a lookup of the video gives."""

    features = ListedSource.features | {Feature.CHAPTERS, Feature.CATALOGUE_REFRESH}

    def __init__(self):
        super().__init__()
        self.chapters: dict[str, tuple[Chapter, ...]] = {}
        self.looked_up: list[str] = []
        self.refresh = ItemRefresh()
        self.asked: list[list[str]] = []

    def video_details(self, url):
        slug = url.rsplit("=", 1)[1]
        self.looked_up.append(slug)
        video = next(video for video in self.videos if video.slug == slug)
        return replace(video, chapters=self.chapters.get(slug, ()))

    def refresh_items(self, url, items):
        self.asked.append([item.slug for item in items])
        return self.refresh


@pytest.fixture
def chapters_source(monkeypatch):
    from sources import registry

    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    return registry.register(ChaptersSource())


def _collection(session, *, split=True):
    from backend.db.models import Collection

    collection = Collection(
        uuid="uuid-albums", slug="albums", source_key="listed", title="Game Music", sharing_url=ALBUMS,
        membership_level="FREE", type="music", episode_identifier="date_based", author_name="Game Music",
        author_slug="game-music", split_chapters=split,
    )
    session.add(collection)
    session.commit()
    return collection


def _index(session, collection, source):
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    return index_listed_collection(session, collection_id=collection.id, source=source)


def _episodes(session):
    from backend.db.models import Episode

    session.expire_all()
    return [
        (episode.source_slug, episode.season.name, episode.episode_identifier, episode.title, episode.duration,
         episode.part_of, episode.part_start, episode.part_end)
        for episode in session.scalars(select(Episode).order_by(Episode.index))
    ]


def _album(slug="album1"):
    return replace(_video(slug, 2024, 3), title="Lofi Album")


def test_a_video_with_chapters_becomes_a_season_with_an_episode_per_chapter(chapters_source, session):
    chapters_source.videos = [_album(), _video("single", 2024, 5)]
    chapters_source.chapters = {"album1": CHAPTERS}
    collection = _collection(session)

    assert _index(session, collection, chapters_source) == 4

    assert _episodes(session) == [
        ("album1-part-1", "Lofi Album", "ep.S01E01", "Intro", 95.5, "album1", 0.0, 95.5),
        ("album1-part-2", "Lofi Album", "ep.S01E02", "Rain", 164.5, "album1", 95.5, 260.0),
        ("album1-part-3", "Lofi Album", "ep.S01E03", "Outro", 40.0, "album1", 260.0, 300.0),
        ("single", "2024", "ep.2024-05-01T00:00:00.000000", "Video single", 60.0, None, None, None),
    ]
    # The listing said nothing about chapters, so each new video was looked up once.
    assert chapters_source.looked_up == ["album1", "single"]

    # The next index knows the album by its video.
    assert _index(session, collection, chapters_source) == 0
    assert "album1" in chapters_source.known_seen[-1]


def test_the_parts_are_the_tracks_of_an_album(chapters_source, session):
    from backend.db.models import Episode
    from backend.utils.music import music_track

    chapters_source.videos = [_album()]
    chapters_source.chapters = {"album1": CHAPTERS}
    _index(session, _collection(session), chapters_source)

    session.expire_all()
    rain = session.scalars(select(Episode).where(Episode.title == "Rain")).one()
    track = music_track(rain)
    assert (track.album, track.track_number, track.track_count) == ("Lofi Album", 2, 3)


def test_videos_stay_whole_unless_the_collection_splits_them(chapters_source, session):
    chapters_source.videos = [_album()]
    chapters_source.chapters = {"album1": CHAPTERS}

    _index(session, _collection(session, split=False), chapters_source)

    assert [row[0] for row in _episodes(session)] == ["album1"]
    assert chapters_source.looked_up == []


def test_the_source_is_asked_about_the_whole_video_and_the_parts_keep_their_titles(chapters_source, session):
    from task_manager.tasks.helpers.listed_collections import refresh_listed_collection

    chapters_source.videos = [_album()]
    chapters_source.chapters = {"album1": CHAPTERS}
    collection = _collection(session)
    _index(session, collection, chapters_source)

    chapters_source.refresh = ItemRefresh(details={"album1": replace(_album(), title="Renamed", duration=900.0)})
    refresh_listed_collection(session, collection_id=collection.id, source=chapters_source)
    assert chapters_source.asked == [["album1"]]
    assert [(row[3], row[4]) for row in _episodes(session)] == [("Intro", 95.5), ("Rain", 164.5), ("Outro", 40.0)]

    chapters_source.refresh = ItemRefresh(removed=frozenset({"album1"}))
    counts = refresh_listed_collection(session, collection_id=collection.id, source=chapters_source)
    assert counts.removed == 3


def test_a_part_downloads_only_its_own_stretch_of_the_video():
    from downloader import DownloadError
    from downloader.ytdlp import resolve_ytdlp_source

    source = resolve_ytdlp_source(
        "https://www.youtube.com/watch?v=album1", command=("yt-dlp",), preferred_format="format_audio_only",
        audio_only=True, section=(95.5, 260.0),
    )
    command = source.ytdlp_command
    assert command[command.index("--download-sections") + 1] == "*95.500-260.000"

    with pytest.raises(DownloadError):
        resolve_ytdlp_source(
            "https://www.youtube.com/watch?v=album1", command=("yt-dlp",), preferred_format="format_hls",
            audio_only=False, section=(95.5, 260.0),
        )


def test_a_feed_never_streams_a_part_from_the_site():
    from backend.services.stream_episodes import can_stream_from_source

    profile = SimpleNamespace(use_source_stream=True, collection=SimpleNamespace(site_key=None))
    assert can_stream_from_source(profile, SimpleNamespace(part_of="album1")) is False


def test_the_upgrade_check_does_not_compare_a_part_with_the_whole_videos_length(monkeypatch):
    from backend.db.models import Episode
    from backend.services import upgrade_check
    from backend.services.upgrade_check import upgrade_findings
    from sources import UpgradeOffer

    monkeypatch.setattr(upgrade_check, "ytdlp_quality", lambda _profile: SimpleNamespace(video_codecs=(), strict=False))
    part = Episode(part_of="album1", part_start=95.5, part_end=260.0, duration=164.5)
    download = SimpleNamespace(
        media=part, duration=164.5, sponsorblock_segments=(), redownload_when_final=False, video_height=None,
        video_codec=None, subtitle_languages=None,
    )
    profile = SimpleNamespace(upgrade_improvements=["length", "sponsorblock"])
    local = SimpleNamespace(preferred_format="format_audio_only", subtitle_mode="no_subtitles")
    site = SimpleNamespace(upgrade_checks=SimpleNamespace(improvements=(
        SimpleNamespace(value="length"), SimpleNamespace(value="sponsorblock"),
    )))
    offer = UpgradeOffer(videos=(), duration=300.0, sponsorblock=())

    findings = upgrade_findings(offer, download, profile, local, site)
    assert (findings.improvements, findings.could_improve) == ((), False)
