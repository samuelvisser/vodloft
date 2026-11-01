"""Ownership: each user's own Quick downloads and Stream Profiles, and who added what."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.security.access import TEMPLATES, Access, Area, Level


@pytest.fixture
def session():
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _user(user_id: int, template: str = "downloader", **levels) -> Access:
    resolved = {**TEMPLATES[template].levels}
    resolved.update(levels)
    return Access.for_user(
        user_id=user_id, username=f"user{user_id}", levels=resolved, source_limits=None,
        members_only=False, delete_files=False, must_change_password=False,
        template_key=template, session_version=1,
    )


def _add_users(session, *ids: int):
    from backend.db.models import User

    for user_id in ids:
        session.add(User(id=user_id, username=f"user{user_id}", password_hash="x"))
    session.flush()


# Quick downloads -------------------------------------------------------------


def _manifest(quick_id: str, owner: str | None):
    from downloader.storage.quick import QuickManifest

    now = datetime.now(timezone.utc)
    return QuickManifest(
        id=quick_id, title=quick_id, file_name=f"{quick_id}.mp4", size_bytes=1, format="Video",
        created_at=now, expires_at=now + timedelta(hours=1), owner=owner,
    )


@pytest.fixture
def ready_files(monkeypatch):
    from backend.api.endpoints.quick_downloads import service

    folders = {
        "mine": SimpleNamespace(manifest=_manifest("mine", "1"), file=None),
        "theirs": SimpleNamespace(manifest=_manifest("theirs", "2"), file=None),
        "before-accounts": SimpleNamespace(manifest=_manifest("before-accounts", None), file=None),
    }
    monkeypatch.setattr(service, "_ready", lambda: list(folders.values()))
    monkeypatch.setattr(service, "active_quick_download_operations", lambda s: [])
    monkeypatch.setattr(service, "ready_quick_download", lambda quick_id: folders.get(quick_id))
    discarded: list[str] = []
    monkeypatch.setattr(service, "discard_quick_download", lambda quick_id: discarded.append(quick_id) or True)
    return discarded


def test_users_see_only_their_own_ready_files(session, ready_files):
    from backend.api.endpoints.quick_downloads.service import list_quick_downloads

    assert [f.id for f in list_quick_downloads(session, _user(1)).ready] == ["mine"]
    everyone = _user(9, **{Area.QUICK_DOWNLOADS: Level.MANAGE})
    assert {f.id for f in list_quick_downloads(session, everyone).ready} == {"mine", "theirs", "before-accounts"}
    assert {f.id for f in list_quick_downloads(session, Access.full()).ready} == {"mine", "theirs", "before-accounts"}


def test_someone_elses_file_cannot_be_fetched_or_deleted(session, ready_files):
    from backend.api.endpoints.quick_downloads.service import file_delivery, remove_quick_download

    assert file_delivery(_user(1), "theirs", None) is None
    assert remove_quick_download(session, _user(1), "theirs") is False
    assert remove_quick_download(session, _user(1), "mine") is True
    assert ready_files == ["mine"]


def test_history_is_kept_per_user(session):
    from backend.db.models import QuickDownloadHistory
    from backend.services import quick_download_history as history

    for quick_id, owner in (("a", "1"), ("b", "2"), ("c", None)):
        session.add(QuickDownloadHistory(
            quick_download_id=quick_id, title=quick_id, source_key="ytdlp", source_name="yt-dlp", url="u",
            format="Video", choice={}, outcome="downloaded", owner=owner,
        ))
    session.flush()
    assert [row.quick_download_id for row in history.list_history(session, owner="1", everyone=False)] == ["a"]
    assert len(history.list_history(session)) == 3
    assert history.clear_history(session, owner="1", everyone=False) == 1
    assert sorted(row.quick_download_id for row in history.list_history(session)) == ["b", "c"]


def test_a_quick_download_remembers_its_owner():
    from backend.api.endpoints.quick_downloads.service import owner_of

    assert owner_of(_user(7)) == "7"
    assert owner_of(Access.full()) is None


# Stream Profiles -------------------------------------------------------------


class _Request:
    base_url = SimpleNamespace(scheme="https", netloc="vodloft.test", path="/")
    method = "GET"


def _show(session):
    from backend.db.models import Show

    show = Show(
        source_key="dailywire", uuid="u", slug="show", title="Show", description="", sharing_url="https://x/show",
        membership_level="FREE", type="podcast", episode_identifier="numbered", author_name="A", author_slug="a",
    )
    session.add(show)
    session.flush()
    return show


def _profile(session, access, show):
    from backend.api.endpoints.rss_stream_profiles.service import create_stream_profile_rss
    from backend.api.models.rss_stream_profile import RssStreamProfileAPICreate

    return create_stream_profile_rss(session, _Request(), RssStreamProfileAPICreate(
        show_id=show.id, title="Show", enable_profile=True, use_downloads=True, use_dw_stream=False,
        preferred_format="format_1080p", prefer_exact_match=False, feed_url="https://vodloft.test/feed",
    ), access)


def test_stream_profiles_belong_to_whoever_made_them(session, monkeypatch):
    from backend.api.endpoints.rss_stream_profiles import service as rss
    from backend.api.endpoints.stream_profiles.service import get_stream_profiles_list

    monkeypatch.setattr(rss, "ensure_source_can_stream", lambda show, use_dw_stream: None)
    _add_users(session, 1, 2)
    show = _show(session)
    mine = _profile(session, _user(1, "viewer"), show)
    theirs = _profile(session, _user(2, "viewer"), show)

    assert [p.id for p in get_stream_profiles_list(session, _user(1, "viewer"))] == [mine.id]
    assert [p.id for p in rss.get_rss_stream_profiles_list(session, _user(1, "viewer"))] == [mine.id]
    with pytest.raises(HTTPException) as hidden:
        rss.get_stream_profile_rss(session, _user(1, "viewer"), theirs.id)
    assert hidden.value.status_code == 404
    with pytest.raises(HTTPException):
        rss.delete_stream_profile_rss(session, _user(1, "viewer"), theirs.id)
    assert {p.id for p in get_stream_profiles_list(session, Access.full())} == {mine.id, theirs.id}


def test_a_disabled_users_feeds_stop_answering(session, monkeypatch):
    from backend.api.endpoints.feeds.service import get_rss_stream_profile_by_token
    from backend.api.endpoints.rss_stream_profiles import service as rss
    from backend.db.models import RssStreamProfile, User

    monkeypatch.setattr(rss, "ensure_source_can_stream", lambda show, use_dw_stream: None)
    _add_users(session, 1)
    profile = session.get(RssStreamProfile, _profile(session, _user(1, "viewer"), _show(session)).id)
    assert get_rss_stream_profile_by_token(session, profile.token).id == profile.id
    session.get(User, 1).is_enabled = False
    session.flush()
    with pytest.raises(HTTPException) as gone:
        get_rss_stream_profile_by_token(session, profile.token)
    assert gone.value.status_code == 404


def test_profiles_from_before_accounts_go_to_the_first_administrator(session, monkeypatch):
    from backend.api.endpoints.rss_stream_profiles import service as rss
    from backend.db.models import RssStreamProfile, Settings
    from backend.services import users

    monkeypatch.setattr(rss, "ensure_source_can_stream", lambda show, use_dw_stream: None)
    session.add(Settings())
    profile = _profile(session, Access.full(), _show(session))
    admin = users.set_accounts_enabled(session, True, first_administrator=("sam", "hash"))
    assert session.get(RssStreamProfile, profile.id).owner_user_id == admin.id


@pytest.mark.parametrize(("choice", "kept"), [("transfer", True), ("delete", False)])
def test_deleting_a_user_transfers_or_deletes_their_profiles(session, monkeypatch, choice, kept):
    from backend.api.endpoints.rss_stream_profiles import service as rss
    from backend.db.models import RssStreamProfile, User
    from backend.services import users

    monkeypatch.setattr(rss, "ensure_source_can_stream", lambda show, use_dw_stream: None)
    _add_users(session, 1, 2)
    profile_id = _profile(session, _user(2, "viewer"), _show(session)).id
    users.delete_user(session, session.get(User, 2), stream_profiles=choice, heir_id=1)
    remaining = session.get(RssStreamProfile, profile_id)
    assert (remaining is not None) is kept
    if kept:
        assert remaining.owner_user_id == 1


# Who added it ----------------------------------------------------------------


def test_shows_remember_who_added_them(session):
    from task_manager.scheduler.requester import current_requester

    _add_users(session, 5)
    token = current_requester.set(5)
    try:
        show = _show(session)
    finally:
        current_requester.reset(token)
    assert show.created_by_user_id == 5
    session.expunge_all()
    from backend.db.models import Show
    session.add(Show(
        source_key="dailywire", uuid="u2", slug="other", title="Other", description="", sharing_url="https://x/o",
        membership_level="FREE", type="podcast", episode_identifier="numbered", author_name="A", author_slug="a",
    ))
    session.flush()
    assert session.query(Show).filter_by(slug="other").one().created_by_user_id is None


def test_a_feed_streams_only_what_its_owner_may_use(session, monkeypatch):
    from backend.api.endpoints.feeds import service as feeds
    from backend.api.endpoints.rss_stream_profiles import service as rss
    from backend.db.models import RssStreamProfile, User

    monkeypatch.setattr(rss, "ensure_source_can_stream", lambda show, use_dw_stream: None)
    _add_users(session, 1)
    profile = session.get(RssStreamProfile, _profile(session, _user(1, "viewer"), _show(session)).id)
    profile.show.membership_level = "PREMIUM"
    asked: list[bool] = []

    class Source:
        name = "Fake"

        def episode_media(self, *, slug, members_only, interactive=False):
            asked.append(members_only)
            return SimpleNamespace(audio_url="https://cdn/a.m4a", video_url="https://cdn/v.mp4")

    episode = SimpleNamespace(slug="ep", source_key="dailywire")
    feeds.get_source_stream_url(profile, episode, media_kind="audio", source=Source())
    session.get(User, 1).members_only = True
    feeds.get_source_stream_url(profile, episode, media_kind="audio", source=Source())
    assert asked == [False, True]


# Each user's own Quick download defaults -------------------------------------


_OWN = {
    "default_kind": "audio", "default_quality": "720p", "default_container": "mkv", "default_codec": "auto",
    "default_audio_format": "mp3", "default_mp3_bitrate": 128, "embed_metadata": False, "embed_artwork": True,
}


def _quick_settings(monkeypatch, **changes):
    from backend.api.endpoints.quick_downloads import service
    from config import get_settings

    quick = get_settings().quick_download.model_copy(update=changes)
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(quick_download=quick))
    return quick


def test_users_keep_their_own_quick_download_defaults(session, monkeypatch):
    from backend.api.endpoints.quick_downloads.service import quick_download_settings_for, save_quick_download_preferences
    from backend.api.models.settings import QuickDownloadPreferencesValue

    install = _quick_settings(monkeypatch, lock_to_defaults=False, max_quality="1080p")
    _add_users(session, 1, 2)
    saved = save_quick_download_preferences(session, _user(1), QuickDownloadPreferencesValue.model_validate(_OWN))
    assert saved.own_defaults and saved.default_kind == "audio" and saved.default_mp3_bitrate == 128
    # The install's rules still apply to them.
    assert saved.max_quality == "1080p"
    # Someone else, and the install without accounts, keep the install's defaults.
    assert not quick_download_settings_for(session, _user(2)).own_defaults
    assert quick_download_settings_for(session, Access.full()).default_kind == install.default_kind

    forgotten = save_quick_download_preferences(session, _user(1), None)
    assert not forgotten.own_defaults and forgotten.default_kind == install.default_kind


def test_locked_defaults_win_over_a_users_own(session, monkeypatch):
    from backend.api.endpoints.quick_downloads.service import quick_download_settings_for, save_quick_download_preferences
    from backend.api.models.settings import QuickDownloadPreferencesValue

    _quick_settings(monkeypatch, lock_to_defaults=False)
    _add_users(session, 1)
    save_quick_download_preferences(session, _user(1), QuickDownloadPreferencesValue.model_validate(_OWN))
    install = _quick_settings(monkeypatch, lock_to_defaults=True)
    locked = quick_download_settings_for(session, _user(1))
    assert not locked.own_defaults and locked.default_kind == install.default_kind


def test_own_defaults_need_an_account(session):
    from backend.api.endpoints.quick_downloads.service import PreferencesNeedAnAccount, save_quick_download_preferences

    with pytest.raises(PreferencesNeedAnAccount):
        save_quick_download_preferences(session, Access.full(), None)


def test_everyones_quick_downloads_say_who_asked(session, ready_files):
    from backend.api.endpoints.quick_downloads.service import list_quick_downloads

    _add_users(session, 1, 2)
    everyone = _user(9, **{Area.QUICK_DOWNLOADS: Level.MANAGE})
    names = {f.id: f.owner_name for f in list_quick_downloads(session, everyone).ready}
    assert names == {"mine": "user1", "theirs": "user2", "before-accounts": None}
    assert [f.owner_name for f in list_quick_downloads(session, _user(1)).ready] == [None]


def test_shows_say_who_added_them(session):
    from backend.api.models.show import ShowAPIRead
    from backend.db.models import Show
    from task_manager.scheduler.requester import current_requester

    _add_users(session, 5)
    token = current_requester.set(5)
    try:
        show_id = _show(session).id
    finally:
        current_requester.reset(token)
    session.expire_all()
    assert ShowAPIRead.model_validate(session.get(Show, show_id)).added_by == "user5"
