"""Matching files already on disk to episodes, and adopting them."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from conftest import use_database

from importer.existing_files import (
    EpisodeFacts,
    FoundFile,
    is_media_file,
    match_files,
    normalise,
    scan_folder,
    template_patterns,
)

FOLDER = "/downloads/YouTube/Veritasium"
TEMPLATE = "/downloads/YouTube/{{ collection_title }}/{{ date }} {{ title }} [{{ episode_site_id }}].ext"


def _facts(episode_id: int, title: str, site_id: str, day: date, **extra) -> EpisodeFacts:
    return EpisodeFacts(
        episode_id, title, site_id, day, values={
            "collection_title": "Veritasium", "date": day.isoformat(), "title": title, "episode_site_id": site_id,
            "year": str(day.year),
        }, **extra,
    )


EPISODES = [
    _facts(1, "The Surprising Genius of Sewing Machines", "RDOMKIw1aF4", date(2024, 3, 2)),
    _facts(2, "Why Machines That Bend Are Better", "97t7Xj_iBv0", date(2019, 11, 8)),
    _facts(3, "What is NOT Random?", "sMb00lz-IfE", date(2016, 5, 14)),
]


# Normalising and patterns -----------------------------------------------------

def test_names_compare_without_the_filename_modes_replacements():
    assert normalise("Amélie： Test？") == normalise("Amelie_-_Test") == normalise("Amélie: Test?") == "amelie test"
    assert normalise("Part 1⧸Part 2") == "part 1 part 2"


def test_a_template_reads_values_back_out_of_a_path():
    (pattern,) = template_patterns(TEMPLATE)

    readings = list(pattern.read("downloads/youtube/veritasium/2024 03 02 the surprising genius of sewing machines rdomkiw1af4"))

    assert {
        "collection_title": "veritasium", "date": "2024 03 02",
        "title": "the surprising genius of sewing machines", "episode_site_id": "rdomkiw1af4",
    } in readings


def test_each_branch_of_a_template_is_a_pattern():
    patterns = template_patterns("/downloads/{% if year %}{{ year }}/{% endif %}{{ title }}.ext")

    assert len(patterns) == 2


def test_a_template_without_variables_reads_nothing():
    assert template_patterns("/downloads/fixed.ext") == ()


def test_a_template_that_only_reads_a_date_matches_nothing():
    # The channel and title go through filters the pattern can't read back, so only the date is left:
    # that would fit every file of that day in a folder several channels share.
    template = ("/downloads/YouTube/{{ collection_title | replace(' ', '_') }}/"
                "{{ date }} [{{ title | replace(' ', '_') }}].ext")
    assert template_patterns(template) == ()
    assert len(template_patterns("/downloads/Show/S{{ season_number }}E{{ episode_number }}.ext")) == 1

    files = [FoundFile("Matt's Off Road Recovery/2024-03-02 [We_Opened_The_Wrecker_s_Hubs].mp4", 1)]
    (match,) = _match(files, patterns=template_patterns(template)).values()
    assert match.evidence != "template"


# Scanning ---------------------------------------------------------------------

def test_scanning_finds_media_and_their_sidecars_and_skips_partial_files(tmp_path):
    for name in (
        "A [x].mp4", "A [x].info.json", "A [x].en.srt", "B.mkv.part", "C.f137.mp4", "C.ytdl", ".vodloft-replace-1.part",
        "notes.txt", "sub/D.m4a",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "E.mp4").write_bytes(b"x")

    found = scan_folder(tmp_path)

    assert [(file.path, file.sidecars) for file in found] == [
        ("A [x].mp4", ("A [x].en.srt", "A [x].info.json")),
        ("sub/D.m4a", ()),
    ]
    assert not is_media_file("Video.temp.mp4.part")


# Matching ---------------------------------------------------------------------

def _match(files, episodes=EPISODES, **kwargs):
    return {item.path.rsplit("/", 1)[-1]: item for item in match_files(files, episodes, folder=FOLDER, **kwargs).files}


def test_strongest_evidence_first():
    sidecars = {f"{FOLDER}/clip.info.json": b'{"id": "sMb00lz-IfE"}'}
    files = [
        FoundFile("recorded.mp4", 1),
        FoundFile("2024-03-02 Sewing [RDOMKIw1aF4].mp4", 1),
        FoundFile("clip.mp4", 1, ("clip.info.json",)),
        FoundFile("unknown.mp4", 1),
    ]

    matches = _match(files, recorded={f"{FOLDER}/recorded.mp4": 2}, read=sidecars.get)

    assert (matches["recorded.mp4"].episode_id, matches["recorded.mp4"].evidence) == (2, "recorded")
    assert (matches["2024-03-02 Sewing [RDOMKIw1aF4].mp4"].evidence, matches["2024-03-02 Sewing [RDOMKIw1aF4].mp4"].confidence) == ("id_in_name", "certain")
    assert (matches["clip.mp4"].episode_id, matches["clip.mp4"].evidence) == (3, "sidecar")
    assert matches["unknown.mp4"].episode_id is None


def test_expected_path_is_certain():
    episodes = [_facts(1, "Sewing", "RDOMKIw1aF4", date(2024, 3, 2), expected_path=f"{FOLDER}/Sewing machines")]

    matches = _match([FoundFile("Sewing machines.webm", 1)], episodes)

    assert matches["Sewing machines.webm"].evidence == "expected_path"


def test_template_pattern_is_likely_and_works_through_filename_modes():
    files = [
        FoundFile("2019-11-08 Why Machines That Bend Are Better.mkv", 1),
        FoundFile("2016-05-14_What_is_NOT_Random.mp4", 1),
    ]

    matches = _match(files, patterns=template_patterns("/downloads/YouTube/{{ collection_title }}/{{ date }} {{ title }}.ext"))

    assert (matches["2019-11-08 Why Machines That Bend Are Better.mkv"].episode_id, matches["2019-11-08 Why Machines That Bend Are Better.mkv"].confidence) == (2, "likely")
    assert matches["2016-05-14_What_is_NOT_Random.mp4"].episode_id == 3


def test_title_and_date_needs_review():
    matches = _match([FoundFile("2016-05-15 What is NOT Random？ (1).mp4", 1)])

    item = matches["2016-05-15 What is NOT Random？ (1).mp4"]
    assert (item.episode_id, item.evidence, item.confidence) == (3, "title_date", "review")


def test_two_files_for_one_episode_are_never_certain():
    files = [FoundFile("A [RDOMKIw1aF4].mp4", 1), FoundFile("B [RDOMKIw1aF4].mkv", 1)]

    matches = _match(files)

    assert {item.confidence for item in matches.values()} == {"review"}
    assert all(item.note == "Another file matches this episode too" for item in matches.values())


def test_stronger_evidence_keeps_the_episode():
    files = [FoundFile("A [RDOMKIw1aF4].mp4", 1), FoundFile("2024-03-02 The Surprising Genius of Sewing Machines.mp4", 1)]

    matches = _match(files)

    assert matches["A [RDOMKIw1aF4].mp4"].confidence == "certain"
    assert matches["2024-03-02 The Surprising Genius of Sewing Machines.mp4"].confidence == "review"


def test_one_file_that_fits_several_episodes_goes_to_review():
    episodes = [_facts(1, "Same", "a1", date(2024, 1, 1)), _facts(2, "Same", "b2", date(2024, 1, 1))]

    matches = _match([FoundFile("2024-01-01 Same.mp4", 1)], episodes,
                     patterns=template_patterns("/downloads/YouTube/{{ collection_title }}/{{ date }} {{ title }}.ext"))

    item = matches["2024-01-01 Same.mp4"]
    assert (item.episode_id, item.confidence, item.candidates) == (None, "review", (1, 2))


# The application --------------------------------------------------------------

def _session() -> Session:
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine)


@pytest.fixture
def library(tmp_path, monkeypatch):
    from backend.db.models import Collection, DownloadProfile, Episode, LocalMediaProfile, Season
    from backend.types.collection_types import CollectionType, EpisodeIdentifier
    from backend.types.media_types import MediaType
    from config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings.download_settings, "download_root", tmp_path)
    session = _session()
    use_database(session.get_bind())
    collection = Collection(
        source_key="ytdlp", uuid="c", slug="veritasium", title="Veritasium", description="",
        sharing_url="https://www.youtube.com/@veritasium", membership_level="FREE", type=CollectionType.SERIES.value,
        episode_identifier=EpisodeIdentifier.NUMBERED.value, author_name="Veritasium", author_slug="veritasium",
    )
    season = Season(collection=collection, index=1, slug="season-1", name="Season 1")
    episodes = []
    for index, (title, site_id, day) in enumerate((
        ("The Surprising Genius of Sewing Machines", "RDOMKIw1aF4", date(2024, 3, 2)),
        ("Why Machines That Bend Are Better", "97t7Xj_iBv0", date(2019, 11, 8)),
        ("What is NOT Random?", "sMb00lz-IfE", date(2016, 5, 14)),
        ("Not on disk", "zzzzzzzzzzz", date(2025, 1, 1)),
    ), start=1):
        episodes.append(Episode(
            source_key="ytdlp", uuid=f"e{index}", type=MediaType.EPISODE.value, collection=collection, season=season,
            index=index, episode_identifier=f"ep.{index}", slug=f"episode-{index}", source_slug=site_id, title=title,
            description="", duration=60, publish_status="published_final",
            sharing_url=f"https://www.youtube.com/watch?v={site_id}",
            published_date=datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc),
        ))
    profile = LocalMediaProfile(slug="yt", name="YouTube", output_template=TEMPLATE, preferred_format="format_1080p")
    download_profile = DownloadProfile(collection=collection, local_media_profile=profile, enable_profile=True)
    session.add_all([collection, season, *episodes, profile, download_profile])
    session.flush()

    folder = tmp_path / "YouTube" / "Veritasium"
    folder.mkdir(parents=True)
    (folder / "2024-03-02 The Surprising Genius of Sewing Machines [RDOMKIw1aF4].mp4").write_bytes(b"a" * 100)
    (folder / "2024-03-02 The Surprising Genius of Sewing Machines [RDOMKIw1aF4].jpg").write_bytes(b"jpg")
    (folder / "2024-03-02 The Surprising Genius of Sewing Machines [RDOMKIw1aF4].en.srt").write_bytes(b"1")
    (folder / "2019-11-08 Why Machines That Bend Are Better.mkv").write_bytes(b"b" * 100)
    (folder / "2016-05-15 What is NOT Random？.mp4").write_bytes(b"c" * 100)
    (folder / "bonus.mp4").write_bytes(b"d")
    session.commit()
    return session, collection, profile, download_profile, episodes, tmp_path


def _scan(session, collection, profile, download_profile, **kwargs):
    from backend.services import existing_files

    scan = existing_files.request_scan(
        session, collection, profile, folder="/downloads/YouTube/Veritasium", hold=[download_profile], **kwargs,
    )
    session.commit()
    return scan


def test_scan_matches_adopts_and_releases_the_download_profile(library, monkeypatch):
    from backend.db.models import EpisodeMediaDownload, MediaDownloadHistory
    from backend.services import existing_files

    session, collection, profile, download_profile, episodes, root = library
    queued = []
    monkeypatch.setattr(existing_files, "queue_scan", lambda *args: queued.append(args))

    scan = _scan(session, collection, profile, download_profile,
                 template="/downloads/YouTube/{{ collection_title }}/{{ date }} {{ title }}.ext")
    assert (scan.status, download_profile.enable_profile, len(queued)) == ("scanning", False, 1)

    counts = existing_files.run_scan(collection_id=collection.id, local_media_profile_id=profile.id)
    session.expire_all()
    assert counts == {"files": 4, "certain": 1, "likely": 1, "review": 1}

    view = existing_files.scan_view(session, scan)
    assert view["counts"] == {"certain": 1, "likely": 1, "review": 1, "unmatched": 1, "adopted": 0}
    assert view["episodes_without_file"] == 2
    by_name = {item["path"].rsplit("/", 1)[-1]: item for item in view["files"]}
    assert by_name["2019-11-08 Why Machines That Bend Are Better.mkv"]["matched_by"] == "Template"

    certain = [(item["path"], item["episode"]["id"]) for item in view["files"] if item["confidence"] in ("certain", "likely")]
    result = existing_files.adopt_matches(session, scan, certain)
    session.commit()
    assert result == {"adopted": 2, "errors": []}

    download = session.scalar(select(EpisodeMediaDownload).where(EpisodeMediaDownload.media_item_id == episodes[0].id))
    assert download.artifact_status == "available"
    assert download.artifact_size_bytes == 100 and len(download.artifact_fingerprint) == 64
    assert Path(download.file_path).is_relative_to(root)
    assert sorted((asset.asset_key, asset.kind) for asset in download.assets) == [
        ("artwork", "thumbnail"), ("subtitles-en", "subtitle"),
    ]
    history = session.scalar(select(MediaDownloadHistory).where(MediaDownloadHistory.media_download_id == download.id))
    # The file has the name the profile's template gives it.
    assert (history.action, history.event_metadata["matched_by"]) == ("imported", "Expected path")

    # Adopting the same match again changes nothing; a second file for the episode is refused.
    again = existing_files.adopt_matches(session, scan, certain[:1])
    assert again["errors"] == []
    other = existing_files.adopt_matches(session, scan, [(by_name["bonus.mp4"]["path"], episodes[0].id)])
    assert "already has a file" in other["errors"][0]["error"]

    assert existing_files.finish_scan(session, scan) == 1
    session.commit()
    assert download_profile.enable_profile is True
    assert scan.status == "finished"


def test_a_scan_set_up_with_a_new_collection_waits_for_its_index(library, monkeypatch):
    from backend.services import existing_files

    session, collection, profile, download_profile, _episodes, _root = library
    queued = []
    monkeypatch.setattr(existing_files, "queue_scan", lambda *args: queued.append(args))

    scan = _scan(session, collection, profile, download_profile, wait_for_index=True)
    assert (scan.status, queued) == ("waiting", [])

    assert existing_files.start_waiting_scans(session, collection) == 1
    assert (scan.status, len(queued)) == ("scanning", 1)


def test_adoption_refuses_files_outside_the_download_folder(library, tmp_path_factory):
    from backend.services.adoption import AdoptionError, find_file, real_path

    _session, _collection, _profile, _download_profile, _episodes, _root = library
    outside = tmp_path_factory.mktemp("elsewhere") / "file.mp4"
    outside.write_bytes(b"x")

    with pytest.raises(AdoptionError, match="outside"):
        find_file(outside)
    with pytest.raises(AdoptionError, match="outside"):
        real_path("/downloads/../etc/passwd")


def test_folders_and_default_folder(library):
    from backend.services.existing_files import ExistingFilesError, default_folder, list_folders

    assert default_folder(TEMPLATE) == "/downloads/YouTube"
    assert default_folder("/downloads/{{ title }}.ext") == "/downloads"
    assert default_folder("{% set title = title | lower -%}/downloads/Video/{{ title }}.ext") == "/downloads/Video"
    assert default_folder("/downloads/{% if year %}A/{% else %}A/B/{% endif %}{{ title }}.ext") == "/downloads/A"
    assert list_folders("/downloads") == {"folder": "/downloads/", "parent": None, "folders": ["YouTube"]}
    assert list_folders("/downloads/YouTube")["parent"] == "/downloads/"
    with pytest.raises(ExistingFilesError):
        list_folders("/downloads/missing")


def test_a_collection_review_only_shows_its_own_folder_and_the_profile_review_shows_all(library, monkeypatch):
    from backend.db.models import Collection, DownloadProfile
    from backend.services import existing_files
    from backend.types.collection_types import CollectionType, EpisodeIdentifier

    session, collection, profile, download_profile, _episodes, root = library
    monkeypatch.setattr(existing_files, "queue_scan", lambda *args: None)
    other = Collection(
        source_key="ytdlp", uuid="o", slug="smarter-every-day", title="Smarter Every Day", description="",
        sharing_url="https://www.youtube.com/@smartereveryday", membership_level="FREE",
        type=CollectionType.SERIES.value, episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Destin", author_slug="destin",
    )
    other_download_profile = DownloadProfile(collection=other, local_media_profile=profile, enable_profile=True)
    session.add_all([other, other_download_profile])
    (root / "YouTube" / "Smarter Every Day").mkdir()
    (root / "YouTube" / "Smarter Every Day" / "Slow motion.mp4").write_bytes(b"e")
    session.commit()

    # Both Collections scan the folder they share.
    for owner, holds in ((collection, download_profile), (other, other_download_profile)):
        existing_files.request_scan(session, owner, profile, folder="/downloads/YouTube", hold=[holds])
        session.commit()
        existing_files.run_scan(collection_id=owner.id, local_media_profile_id=profile.id)
        session.expire_all()
    scans = {scan.collection_id: scan for scan in session.scalars(select(existing_files.ExistingFileScan))}

    # A Collection looks in its own folder, the one its show artwork goes in.
    assert existing_files.collection_folder(collection, profile) == "/downloads/YouTube/Veritasium"
    assert existing_files.scan_folder_for(collection, profile) == "/downloads/YouTube/Veritasium"
    assert existing_files.scan_folder_for(other, profile) == "/downloads/YouTube/Smarter Every Day"

    # Veritasium's review lists its own unmatched file, not the one of Smarter Every Day.
    view = existing_files.scan_view(session, scans[collection.id])
    unmatched = sorted(item["path"] for item in view["files"] if item["episode"] is None)
    assert unmatched == ["/downloads/YouTube/Veritasium/bonus.mp4"]
    assert view["counts"]["unmatched"] == 1

    # The profile's review is the whole folder, each file once with its best match.
    review = existing_files.profile_review(session, profile)
    paths = [item["path"] for item in review["files"]]
    assert len(paths) == len(set(paths)) == 5
    assert review["counts"]["unmatched"] == 2
    assert review["counts"]["certain"] == view["counts"]["certain"]
    sewing = next(item for item in review["files"] if "Sewing" in item["path"])
    assert sewing["episode"]["collection_slug"] == "veritasium"
    assert [item["collection_slug"] for item in review["collections"]] == ["smarter-every-day", "veritasium"]


def test_a_profile_scan_looks_for_every_collection_in_its_own_folder(library, monkeypatch):
    from backend.services import existing_files

    session, collection, profile, download_profile, _episodes, _root = library
    queued = []
    monkeypatch.setattr(existing_files, "queue_scan", lambda *args: queued.append(args))

    assert existing_files.scan_profile(session, profile) == 1
    session.commit()
    scan = session.scalar(select(existing_files.ExistingFileScan))
    assert (scan.collection_id, scan.folder, scan.status, len(queued)) == (
        collection.id, "/downloads/YouTube/Veritasium", "scanning", 1,
    )
    # A scan started by hand holds no Download Profile.
    assert download_profile.enable_profile is True


def test_an_adopted_file_belongs_to_the_download_profile_and_its_retention(library):
    """A file adopted for an episode the profile no longer wants is still deleted by its retention, even once missing."""
    from profile_filters import published_days, with_filters

    from backend.db.models import EpisodeMediaDownload
    from backend.services.adoption import adopt, find_file
    from task_manager.tasks.workers.download_profile_worker._helpers import cleanup_older_episodes

    session, _collection, profile, download_profile, episodes, root = library
    with_filters(download_profile, published_days(30))
    download_profile.delete_older_episodes = True
    path = root / "YouTube" / "Veritasium" / "2019-11-08 Why Machines That Bend Are Better.mkv"
    adopted = adopt(session, media=episodes[1], local_media_profile=profile, found=find_file(path))
    assert adopted.download.download_profile_id == download_profile.id

    # Something else deleted the file first.
    path.unlink()
    adopted.download.artifact_status = "missing"
    session.flush()

    assert cleanup_older_episodes(session, download_profile) == 1
    assert session.scalars(select(EpisodeMediaDownload)).all() == []
