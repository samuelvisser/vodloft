"""A cookies file per Site: which file a lookup signs in with, sorting one file into Sites, and the migration."""
from __future__ import annotations

import asyncio
import importlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tests.unit.conftest import use_database

YOUTUBE = "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tyoutube"
TWITCH = ".twitch.tv\tTRUE\t/\tTRUE\t0\tauth-token\ttwitch"
GOOGLE = ".google.com\tTRUE\t/\tTRUE\t0\tNID\tgoogle"
NPO = ".npo.nl\tTRUE\t/\tTRUE\t0\tsession\tnpo"


def _file(*lines: str) -> bytes:
    return ("# Netscape HTTP Cookie File\n" + "".join(f"{line}\n" for line in lines)).encode()


@pytest.fixture
def session():
    from backend.db.core import Base
    import backend.db.models  # noqa: F401  (registers every table)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    use_database(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


def _site(session, key: str, name: str, *domains: str) -> None:
    from backend.db.models import Site

    session.add(Site(key=key, name=name, domains=list(domains)))
    session.commit()


def _stored(site_key: str) -> list[str] | None:
    from sources import cookies

    path = cookies.site_cookies(site_key)
    return cookies.cookie_lines(path.read_text()) if path is not None else None


def test_yt_dlp_signs_in_with_the_cookies_file_of_the_links_site():
    from sources import cookies
    from sources.ytdlp.sites import cookies_for

    cookies.store_site_cookies("youtube", [YOUTUBE])
    cookies.store_site_cookies("npo", [NPO])
    assert cookies_for("https://www.youtube.com/watch?v=abc") == cookies.site_cookies_path("youtube")
    assert cookies_for("https://www.youtube.com/watch?v=abc", use=False) is None
    assert cookies_for("https://www.twitch.tv/videos/1") is None
    # A Site a Source is made for has its cookies file whichever Source fetches it.
    assert cookies_for("https://npo.nl/start/afspelen/een-huis-vol_2") == cookies.site_cookies_path("npo")


def test_lookups_pass_the_sites_cookies_file_to_yt_dlp(monkeypatch):
    from sources import YtDlpSource, cookies, ytdlp_runner as runner

    cookies.store_site_cookies("twitch", [TWITCH])
    asked = []

    def run_json(*args, cookies=None):
        asked.append((args[-1], cookies))
        return {"id": "1", "title": "A stream", "webpage_url": args[-1], "extractor_key": "TwitchVod"}

    monkeypatch.setattr(runner, "run_json", run_json)
    YtDlpSource().resolve("https://www.twitch.tv/videos/1")
    assert asked == [("https://www.twitch.tv/videos/1", cookies.site_cookies_path("twitch"))]


def test_a_sites_cookies_file_keeps_only_its_own_cookies(session):
    from backend.services import site_cookies

    _site(session, "twitch", "Twitch", "twitch.tv")
    listing = site_cookies.save_site_cookies(session, "twitch", _file(YOUTUBE, TWITCH))
    assert (listing.has_cookies, listing.cookie_count) == (True, 1)
    assert _stored("twitch") == [TWITCH]
    with pytest.raises(ValueError, match="no cookies for twitch.tv"):
        site_cookies.save_site_cookies(session, "twitch", _file(YOUTUBE))
    with pytest.raises(site_cookies.SiteNotKnownError):
        site_cookies.save_site_cookies(session, "vimeo", _file(TWITCH))
    assert site_cookies.remove_site_cookies(session, "twitch").has_cookies is False
    assert _stored("twitch") is None


def test_one_cookies_file_is_sorted_into_the_sites(session):
    from backend.services import site_cookies
    from sources import cookies

    _site(session, "youtube", "YouTube", "youtube.com")
    _site(session, "twitch", "Twitch", "twitch.tv")
    cookies.store_site_cookies("npo", [NPO])
    result = site_cookies.sort_cookies(session, _file(YOUTUBE, TWITCH, GOOGLE))
    assert [(site.name, site.cookie_count) for site in result.sites] == [("Twitch", 1), ("YouTube", 1)]
    assert result.other_domains == ("google.com",)
    assert (_stored("youtube"), _stored("twitch")) == ([YOUTUBE], [TWITCH])
    # A Site without cookies in the file keeps its own file.
    assert _stored("npo") == [NPO]
    with pytest.raises(ValueError, match="Netscape"):
        site_cookies.sort_cookies(session, b"not a cookies file")


def test_a_cookies_file_adds_the_sites_its_domains_tell(session):
    from backend.db.models import Site
    from backend.services import site_cookies

    result = site_cookies.add_cookies_file(_file(YOUTUBE, TWITCH))
    session.expire_all()
    # youtube.com alone tells YouTube; twitch.tv alone tells no Site, so it waits for a link.
    assert [site.name for site in result.sites] == ["YouTube"]
    assert result.other_domains == ("twitch.tv",)
    assert session.get(Site, "youtube").domains == ["youtube.com"]

    site = site_cookies.site_of_link(session, "https://www.twitch.tv/somechannel")
    site_cookies.add_site(session, site)
    session.commit()
    assert [site.name for site in site_cookies.add_cookies_file(_file(TWITCH)).sites] == ["Twitch"]
    with pytest.raises(site_cookies.SiteLinkError):
        site_cookies.site_of_link(session, "twitch.tv")


def test_every_site_lists_how_it_signs_in(session):
    from backend.services import site_cookies

    _site(session, "youtube", "YouTube", "youtube.com")
    site_cookies.save_site_cookies(session, "youtube", _file(YOUTUBE))
    sites = {site.key: site for site in site_cookies.list_site_sign_ins(session)}
    assert sites["dailywire"].sign_in_source_key == "dailywire"
    assert sites["dailywire"].cookie_source_names == ("yt-dlp",)
    assert sites["npo"].cookie_source_names == ("NPO Start", "yt-dlp") and sites["npo"].cookies_help
    assert (sites["youtube"].cookie_source_names, sites["youtube"].cookie_count) == (("yt-dlp",), 1)


def test_the_migration_gives_each_site_its_own_cookies_file(session, tmp_path, monkeypatch):
    migration = importlib.import_module(
        "backend.db.background_migrations.versions.305a9510537f_cookies_per_site",
    )
    monkeypatch.setattr(migration, "get_config_path", lambda: tmp_path / "config" / "config.yml")
    old_ytdlp = tmp_path / "config" / "yt-dlp" / "cookies.txt"
    old_npo = tmp_path / "config" / "npo" / "cookies.txt"
    old_ytdlp.parent.mkdir(parents=True)
    old_npo.parent.mkdir(parents=True)
    old_ytdlp.write_bytes(_file(YOUTUBE, TWITCH, ".npo.nl\tTRUE\t/\tTRUE\t0\tsession\tfrom-yt-dlp"))
    old_npo.write_bytes(_file(NPO))

    class Context:
        def update_progress(self, *args):
            pass

        def raise_if_canceled(self):
            pass

    asyncio.run(migration.migrate(Context()))
    assert (_stored("youtube"), _stored("npo")) == ([YOUTUBE], [NPO])
    assert not old_ytdlp.exists() and not old_npo.exists()
    kept = old_ytdlp.with_name("cookies-not-sorted.txt").read_text()
    assert TWITCH in kept and YOUTUBE not in kept


def test_pinchflats_cookies_file_is_sorted_into_the_sites(session):
    from backend.services import imports

    imports._import_cookies(session, _file(YOUTUBE, GOOGLE))
    session.commit()
    assert _stored("youtube") == [YOUTUBE]
    with pytest.raises(imports.ImportServiceError, match="no cookies for a Site"):
        imports._import_cookies(session, _file(GOOGLE))
