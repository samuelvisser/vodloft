"""Source and domain limits: what a limited user may look up, search, add and quick download."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.security.access import TEMPLATES, Access, LinkNotAllowed, SourceLimit
from sources import ANY_DOMAIN, Feature, LinkKind, ResolvedLink, SearchResults, Source, registry


class FakeYtdlp(Source):
    """Any site, as yt-dlp; ``/redirect`` links resolve to another site."""

    id = "fake_ytdlp"
    name = "Fake yt-dlp"
    domains = (ANY_DOMAIN,)
    features = frozenset({Feature.SEARCH})

    def resolve(self, url):
        if url.endswith("/redirect"):
            return ResolvedLink(kind=LinkKind.VIDEO, slug="away", url="https://vimeo.com/123", title="Away")
        if "youtu.be/" in url:
            return ResolvedLink(
                kind=LinkKind.VIDEO, slug="short", url="https://www.youtube.com/watch?v=short", title="Short",
            )
        return ResolvedLink(kind=LinkKind.VIDEO, slug="v", url=url, title="Video")

    def search(self, query):
        return SearchResults(results=[
            ResolvedLink(kind=LinkKind.VIDEO, slug="a", url="https://www.youtube.com/watch?v=a", title="A"),
            ResolvedLink(kind=LinkKind.VIDEO, slug="b", url="https://vimeo.com/b", title="B"),
        ])


class FakeMembers(Source):
    id = "fake_members"
    name = "Fake Members"
    domains = ("members.example",)
    features = frozenset({Feature.MEMBERSHIP_LEVELS})

    def resolve(self, url):
        return ResolvedLink(kind=LinkKind.EPISODE, slug="ep", url=url, title="Episode")


@pytest.fixture
def fake_sources(monkeypatch):
    sources = {key: source for key, source in registry._sources.items() if ANY_DOMAIN not in source.domains}
    monkeypatch.setattr(registry, "_sources", sources)
    return registry.register(FakeYtdlp()), registry.register(FakeMembers())


@pytest.fixture
def session():
    from backend.db.core import Base
    import backend.db.models  # noqa: F401  (registers every table)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


def _user(limits: dict[str, tuple[str, ...] | None] | None, *, members_only: bool = False) -> Access:
    template = TEMPLATES["downloader"]
    return Access.for_user(
        user_id=7, username="tim", levels=template.levels,
        source_limits=None if limits is None else {
            key: SourceLimit(key, domains) for key, domains in limits.items()
        },
        members_only=members_only, delete_files=False, must_change_password=False,
        template_key="downloader", session_version=1,
    )


YOUTUBE_ONLY = {"fake_ytdlp": ("youtube.com", "youtu.be")}


def test_domains_match_the_domain_and_its_subdomains():
    access = _user(YOUTUBE_ONLY)
    assert access.allows_link("fake_ytdlp", "https://www.youtube.com/watch?v=x")
    assert access.allows_link("fake_ytdlp", "https://m.youtube.com/watch?v=x")
    assert access.allows_link("fake_ytdlp", "https://youtu.be/x")
    assert not access.allows_link("fake_ytdlp", "https://notyoutube.com/x")
    assert not access.allows_link("fake_ytdlp", "https://vimeo.com/1")
    assert not access.allows_link("fake_members", "https://members.example/ep")


def test_a_source_without_domain_limits_allows_all_its_links():
    access = _user({"fake_members": None})
    assert access.allows_link("fake_members", "https://members.example/ep")
    assert not access.allows_link("fake_ytdlp", "https://www.youtube.com/watch?v=x")


def test_everyone_without_limits_may_use_every_link():
    assert Access.full().allows_link("fake_ytdlp", "https://vimeo.com/1")
    assert _user(None).allows_link("fake_ytdlp", "https://vimeo.com/1")


def test_a_youtube_only_user_may_look_up_youtube_and_short_links(fake_sources, session):
    from backend.api.endpoints.sources.service import resolve_link

    access = _user(YOUTUBE_ONLY)
    assert resolve_link(s=session, access=access, url="https://www.youtube.com/watch?v=x").source.id == "fake_ytdlp"
    assert resolve_link(s=session, access=access, url="youtu.be/short").url == "https://www.youtube.com/watch?v=short"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://vimeo.com/1", "links on vimeo.com with Fake yt-dlp"),
        ("https://members.example/ep", "may not use links on members.example"),
        # The pasted link is allowed, but it resolves to another site.
        ("https://www.youtube.com/redirect", "links on vimeo.com"),
    ],
)
def test_a_youtube_only_user_is_refused_other_links_with_the_reason(fake_sources, session, url, expected):
    from backend.api.endpoints.sources.service import resolve_link

    with pytest.raises(LinkNotAllowed) as refused:
        resolve_link(s=session, access=_user(YOUTUBE_ONLY), url=url)
    assert expected in str(refused.value)
    assert "You may use: Fake yt-dlp (youtube.com, youtu.be)." in str(refused.value)


def test_a_source_the_user_may_not_use_is_refused_by_name(fake_sources, session):
    from backend.api.endpoints.sources.service import resolve_link

    with pytest.raises(LinkNotAllowed, match="may not use Fake yt-dlp"):
        resolve_link(s=session, access=_user({"fake_members": None}), url="https://www.youtube.com/x", source_key="fake_ytdlp")


def test_other_candidate_sources_are_left_out_of_the_answer(fake_sources, session):
    from backend.api.endpoints.sources.service import resolve_link

    full = resolve_link(s=session, access=Access.full(), url="https://members.example/ep")
    assert [candidate.id for candidate in full.candidates] == ["fake_members", "fake_ytdlp"]
    limited = resolve_link(s=session, access=_user({"fake_members": None}), url="https://members.example/ep")
    assert [candidate.id for candidate in limited.candidates] == ["fake_members"]


def test_search_leaves_out_results_on_other_domains(fake_sources):
    from backend.api.endpoints.sources.service import search_source

    ytdlp, members = fake_sources
    assert [r.slug for r in search_source(Access.full(), ytdlp, "x").results] == ["a", "b"]
    assert [r.slug for r in search_source(_user(YOUTUBE_ONLY), ytdlp, "x").results] == ["a"]
    with pytest.raises(LinkNotAllowed):
        search_source(_user({"fake_members": None}), ytdlp, "x")


def test_adding_media_checks_the_link(fake_sources):
    access = _user(YOUTUBE_ONLY)
    access.check_link_at("fake_ytdlp", "https://www.youtube.com/@channel")
    with pytest.raises(LinkNotAllowed):
        access.check_link_at("fake_ytdlp", "https://vimeo.com/channel")
    with pytest.raises(LinkNotAllowed):
        access.check_link_at("fake_members", None)
    # An unknown Source is for the create route itself to refuse.
    access.check_link_at("no_such_source", "https://example.com")


def test_administrators_ignore_source_limits():
    admin = Access.for_user(
        user_id=1, username="admin", levels=TEMPLATES["administrator"].levels,
        source_limits={"fake_members": SourceLimit("fake_members")}, members_only=False,
        delete_files=False, must_change_password=False, template_key="administrator", session_version=1,
    )
    assert admin.source_limits is None
    assert admin.members_only


# Members-only media ----------------------------------------------------------


class _Tracker:
    def preparing(self, _step):
        pass

    def ensure_active(self):
        pass

    def is_canceled(self):
        return False


def _members_request(kind: LinkKind, members_only: bool):
    from backend.services.quick_downloads import QuickDownloadRequest

    return QuickDownloadRequest(
        id="q1", source_key="fake_members", kind=kind, slug="ep", url="https://members.example/ep",
        title="Episode", members_only=members_only,
    )


def test_users_without_the_switch_only_get_what_a_free_account_gets(fake_sources, monkeypatch):
    from downloader import AccessRequiredError
    from backend.services import quick_downloads

    _, members = fake_sources
    asked: list[bool] = []

    def episode_media(*, slug, members_only, interactive=False):
        asked.append(members_only)
        return SimpleNamespace(video_url=None, audio_url=None, drm_protected=False)

    monkeypatch.setattr(members, "episode_media", episode_media)
    monkeypatch.setattr(quick_downloads, "get_settings", lambda: SimpleNamespace(download_settings=SimpleNamespace()))
    rules = quick_downloads.QuickRules()
    with pytest.raises(AccessRequiredError, match="may not use members-only Fake Members media"):
        quick_downloads._resolve_source(members, _members_request(LinkKind.EPISODE, False), _Tracker(), rules)
    assert asked == [False]
    with pytest.raises(AccessRequiredError):
        quick_downloads._resolve_source(members, _members_request(LinkKind.MOVIE, False), _Tracker(), rules)

    asked.clear()
    with pytest.raises(Exception):
        quick_downloads._resolve_source(members, _members_request(LinkKind.EPISODE, True), _Tracker(), rules)
    assert asked == [False, True]


def test_quick_download_requests_carry_the_switch():
    from backend.services.quick_downloads import QuickDownloadRequest

    request = _members_request(LinkKind.EPISODE, False)
    assert QuickDownloadRequest.from_task_input(request.task_input()).members_only is False
