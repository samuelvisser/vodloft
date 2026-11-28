"""Signing in with the user's own account on a yt-dlp Site: what each Site offers, the cookies file a lookup signs in
with, renewing a sign-in, each Site's own sign-in, and the API under Authentication."""
from __future__ import annotations

import time

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import use_database

OWN_TWITCH = (".twitch.tv\tTRUE\t/\tTRUE\t0\tauth-token\told", ".twitch.tv\tTRUE\t/\tTRUE\t0\tunique_id\tbrowser")


class _Answer:
    """What a Site answers a request with."""

    def __init__(self, status: int = 200, data=None, text: str = ""):
        self.status_code = status
        self.ok = status < 400
        self._data = data
        self.text = text

    def json(self):
        if self._data is None:
            raise ValueError("no JSON")
        return self._data


def _site(url: str):
    from sources.ytdlp import sites

    return sites.site_for(url)


@pytest.mark.parametrize(("url", "kind", "fields"), [
    ("https://www.twitch.tv/somebody", "device_code", []),
    ("https://nebula.tv/videos/a-video", "password", ["email", "password"]),
    ("https://curiositystream.com/video/2", "password", ["email", "password"]),
    ("https://watch.dropout.tv/videos/yes-or-no", "password", ["email", "password"]),
    ("https://www.nicovideo.jp/watch/sm9", "password", ["email", "password"]),
    ("https://soundcloud.com/somebody", "token", ["token"]),
])
def test_these_sites_sign_in_with_an_account(url, kind, fields):
    site = _site(url)
    assert site.account_sign_in is not None
    assert site.account_sign_in.kind == kind
    assert [field.key for field in site.account_sign_in.fields] == fields


def test_other_sites_sign_in_with_a_cookies_file_only():
    assert _site("https://www.youtube.com/watch?v=abc").account_sign_in is None
    assert _site("https://www.bilibili.com/video/BV1").account_sign_in is None


def test_a_lookup_signs_in_with_the_account_and_keeps_the_sites_own_cookies():
    from yt_dlp.cookies import YoutubeDLCookieJar

    from sources import cookies, site_accounts
    from sources.ytdlp.sites import cookies_for

    cookies.store_site_cookies("twitch", list(OWN_TWITCH))
    assert cookies_for("https://www.twitch.tv/videos/1") == cookies.site_cookies_path("twitch")

    site_accounts.save("twitch", site_accounts.SignedIn(
        cookies=(site_accounts.cookie_line("twitch.tv", "auth-token", "from-sign-in"),), account="somebody",
    ))
    path = cookies_for("https://www.twitch.tv/videos/1")
    assert path is not None and path != cookies.site_cookies_path("twitch")
    jar = YoutubeDLCookieJar(str(path))
    jar.load()
    # yt-dlp's Twitch extractor reads the token for gql.twitch.tv; the sign-in's wins over the cookies file's.
    found = {cookie.name: cookie.value for cookie in jar.get_cookies_for_url("https://gql.twitch.tv/gql")}
    assert found == {"auth-token": "from-sign-in", "unique_id": "browser"}
    # The Site's own cookies file stays as the user gave it.
    assert cookies.cookie_lines(cookies.site_cookies_path("twitch").read_text()) == list(OWN_TWITCH)
    assert cookies_for("https://www.twitch.tv/videos/1", use=False) is None

    site_accounts.remove("twitch")
    assert cookies_for("https://www.twitch.tv/videos/1") == cookies.site_cookies_path("twitch")


def test_a_sign_in_without_a_cookies_file_signs_in_on_its_own():
    from sources import site_accounts
    from sources.ytdlp.sites import cookies_for

    assert cookies_for("https://nebula.tv/videos/a-video") is None
    site_accounts.save("nebula", site_accounts.SignedIn(
        cookies=(site_accounts.cookie_line("nebula.tv", "nebula_auth.apiToken", "token"),),
    ))
    path = cookies_for("https://nebula.tv/videos/a-video")
    assert path is not None and "nebula_auth.apiToken\ttoken" in path.read_text()


def test_a_sign_in_that_is_due_is_renewed_before_a_lookup(monkeypatch):
    from sources import site_accounts
    from sources.ytdlp import twitch_account
    from sources.ytdlp.sites import cookies_for

    site_accounts.save("twitch", site_accounts.SignedIn(
        cookies=(site_accounts.cookie_line("twitch.tv", "auth-token", "token"),), account="somebody",
        secrets={"access_token": "token"}, renew_at=time.time() - 1,
    ))
    monkeypatch.setattr(twitch_account.requests, "get", lambda *args, **kwargs: _Answer(data={"login": "somebody", "expires_in": 0}))
    cookies_for("https://www.twitch.tv/videos/1")
    renewed = site_accounts.load("twitch")
    assert renewed.renew_at > time.time() and renewed.problem is None

    # Once Twitch no longer accepts the token, the user sees why, and the old cookies stay until they sign in again.
    site_accounts.save("twitch", site_accounts.SignedIn(**{**renewed.__dict__, "renew_at": time.time() - 1}))
    monkeypatch.setattr(twitch_account.requests, "get", lambda *args, **kwargs: _Answer(401, {"message": "invalid access token"}))
    assert "auth-token\ttoken" in cookies_for("https://www.twitch.tv/videos/1").read_text()
    assert site_accounts.load("twitch").problem == "Twitch ended the sign-in. Sign in again with a new code."


def test_twitch_signs_in_once_the_code_is_entered(monkeypatch):
    from sources import DeviceCode, SignInCodeEnded, get_source, site_accounts
    from sources.ytdlp import twitch_account

    answers = iter([
        _Answer(400, {"status": 400, "message": "authorization_pending"}),
        _Answer(data={"access_token": "the-token", "token_type": "bearer"}),
    ])
    sent = []

    def post(url, data=None, **kwargs):
        sent.append(data)
        return next(answers)

    monkeypatch.setattr(twitch_account.requests, "post", post)
    monkeypatch.setattr(twitch_account.requests, "get", lambda *args, **kwargs: _Answer(data={"login": "somebody", "expires_in": 5000000}))
    site = _site("https://www.twitch.tv/somebody")
    code = DeviceCode("device", "ABCDEFGH", "https://www.twitch.tv/activate", 1800, 1)
    status = get_source("ytdlp").finish_code_sign_in(site, code, lambda seconds: False)

    assert (status.signed_in, status.account) == (True, "somebody")
    assert {item["client_id"] for item in sent} == {twitch_account.CLIENT_ID}
    assert "auth-token\tthe-token" in site_accounts.load("twitch").cookies[0]

    monkeypatch.setattr(twitch_account.requests, "post", lambda *args, **kwargs: _Answer(400, {"message": "invalid device code"}))
    with pytest.raises(SignInCodeEnded):
        get_source("ytdlp").finish_code_sign_in(site, code, lambda seconds: False)
    # Cancelling stops it before Twitch is asked again.
    with pytest.raises(SignInCodeEnded):
        get_source("ytdlp").finish_code_sign_in(site, code, lambda seconds: True)


def test_nebula_keeps_the_token_it_gives_and_not_the_password(monkeypatch):
    from sources import SignInRejected, get_source, site_accounts

    monkeypatch.setattr(requests.Session, "post", lambda self, url, **kwargs: _Answer(data={"key": "api-token"}))
    site = _site("https://nebula.tv/videos/a-video")
    status = get_source("ytdlp").sign_in(site, {"email": " me@example.com ", "password": "secret"})
    assert (status.signed_in, status.account) == (True, "me@example.com")
    signed_in = site_accounts.load("nebula")
    assert signed_in.secrets == {} and "nebula_auth.apiToken\tapi-token" in signed_in.cookies[0]

    monkeypatch.setattr(requests.Session, "post", lambda self, url, **kwargs: _Answer(400, {"detail": "no"}))
    with pytest.raises(SignInRejected) as refused:
        get_source("ytdlp").sign_in(site, {"email": "me@example.com", "password": "wrong"})
    assert refused.value.field == "password"
    with pytest.raises(SignInRejected) as empty:
        get_source("ytdlp").sign_in(site, {"email": "me@example.com", "password": ""})
    assert empty.value.field == "password"


def test_curiositystream_says_why_it_did_not_sign_in(monkeypatch):
    from sources import SignInRejected, get_source

    monkeypatch.setattr(requests.Session, "post", lambda self, url, **kwargs: _Answer(
        401, {"error": {"message": {"base": ["Wrong email or password, please try again"]}, "status_code": 401}},
    ))
    with pytest.raises(SignInRejected, match="Wrong email or password"):
        get_source("ytdlp").sign_in(_site("https://curiositystream.com/video/2"), {"email": "me@example.com", "password": "x"})


def test_dropout_signs_in_again_before_its_session_runs_out(monkeypatch):
    from http.cookiejar import Cookie

    from sources import SignInRejected, get_source, site_accounts

    ends = time.time() + 14 * 24 * 60 * 60

    def get(self, url, **kwargs):
        return _Answer(text='<input name="authenticity_token" value="the-token">')

    def post(self, url, data=None, **kwargs):
        assert data["authenticity_token"] == "the-token"
        self.cookies.set_cookie(Cookie(
            0, "_session", "session", None, False, "watch.dropout.tv", False, False, "/", True, True, int(ends),
            False, None, None, {},
        ))
        return _Answer(text="user_has_subscription: 'true'")

    monkeypatch.setattr(requests.Session, "get", get)
    monkeypatch.setattr(requests.Session, "post", post)
    get_source("ytdlp").sign_in(_site("https://watch.dropout.tv/videos/yes-or-no"), {"email": "me@example.com", "password": "secret"})
    signed_in = site_accounts.load("dropout")
    assert "_session\tsession" in signed_in.cookies[0]
    assert signed_in.secrets == {"email": "me@example.com", "password": "secret"}
    assert ends - 3 * 24 * 60 * 60 < signed_in.renew_at < ends

    monkeypatch.setattr(requests.Session, "post", lambda self, url, **kwargs: _Answer(text="user_has_subscription: 'false'"))
    with pytest.raises(SignInRejected, match="no subscription"):
        get_source("ytdlp").sign_in(_site("https://watch.dropout.tv/videos/yes-or-no"), {"email": "me@example.com", "password": "secret"})


def test_niconico_refuses_an_account_that_asks_for_a_one_time_code(monkeypatch):
    from sources import SignInRejected, get_source

    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kwargs: _Answer())
    monkeypatch.setattr(requests.Session, "post", lambda self, url, **kwargs: _Answer(text='<input name="oneTimePw">'))
    with pytest.raises(SignInRejected, match="one-time code"):
        get_source("ytdlp").sign_in(_site("https://www.nicovideo.jp/watch/sm9"), {"email": "me@example.com", "password": "x"})


def test_soundcloud_signs_in_with_the_token_its_website_keeps(monkeypatch):
    from sources import SignInRejected, get_source, site_accounts
    from sources.ytdlp import soundcloud_account

    monkeypatch.setattr(soundcloud_account, "account_of", lambda token: "a-musician" if token == "2-good" else None)
    site = _site("https://soundcloud.com/somebody")
    assert get_source("ytdlp").sign_in(site, {"token": " 2-good "}).account == "a-musician"
    assert "oauth_token\t2-good" in site_accounts.load("soundcloud").cookies[0]
    with pytest.raises(SignInRejected) as refused:
        get_source("ytdlp").sign_in(site, {"token": "2-bad"})
    assert refused.value.field == "token"


def test_a_site_signs_in_only_the_way_it_offers():
    from sources import SignInRejected, get_source

    with pytest.raises(SignInRejected):
        get_source("ytdlp").sign_in(_site("https://www.twitch.tv/somebody"), {"email": "me@example.com"})
    with pytest.raises(SignInRejected):
        get_source("ytdlp").start_code_sign_in(_site("https://nebula.tv/videos/a-video"))


# ---- The API under Authentication ----

@pytest.fixture
def client(monkeypatch):
    from backend.api.endpoints.sources import router as router_module
    from backend.db.core import Base
    from backend.db.models import Site
    import backend.db.models  # noqa: F401  (registers every table)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    use_database(engine)
    with sessionmaker(bind=engine)() as s:
        s.add_all([Site(key="nebula", name="Nebula", domains=["nebula.tv"]), Site(key="twitch", name="Twitch", domains=["twitch.tv"])])
        s.commit()
    changed = []
    monkeypatch.setattr(router_module, "access_changed", changed.append)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1")
    with TestClient(app) as test_client:
        test_client.changed = changed
        yield test_client
    engine.dispose()


def test_signing_in_and_out_under_authentication(client, monkeypatch):
    monkeypatch.setattr(requests.Session, "post", lambda self, url, **kwargs: _Answer(data={"key": "api-token"}))
    listed = {site["key"]: site for site in client.get("/api/v1/sources/authentication").json()}
    assert listed["nebula"]["accountSignIn"]["kind"] == "password"
    assert listed["nebula"]["accountStatus"] == {"signedIn": False, "account": None, "problem": None}

    signed_in = client.put("/api/v1/sources/authentication/nebula/account", json={"values": {"email": "me@example.com", "password": "x"}})
    assert signed_in.status_code == 200
    assert signed_in.json()["accountStatus"]["account"] == "me@example.com"
    assert client.changed == ["ytdlp"]

    signed_out = client.delete("/api/v1/sources/authentication/nebula/account")
    assert signed_out.json()["accountStatus"]["signedIn"] is False


def test_a_refused_sign_in_lands_under_its_field(client, monkeypatch):
    monkeypatch.setattr(requests.Session, "post", lambda self, url, **kwargs: _Answer(400, {"detail": "no"}))
    refused = client.put("/api/v1/sources/authentication/nebula/account", json={"values": {"email": "me@example.com", "password": "x"}})
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["loc"] == ["body", "values", "password"]


def test_signing_in_with_a_code_under_authentication(client, monkeypatch):
    from sources.ytdlp import twitch_account

    monkeypatch.setattr(twitch_account.requests, "post", lambda url, data=None, **kwargs: _Answer(data=(
        {"device_code": "device", "user_code": "ABCDEFGH", "verification_uri": "https://www.twitch.tv/activate", "expires_in": 1800, "interval": 1}
        if url.endswith("/device") else {"access_token": "the-token"}
    )))
    monkeypatch.setattr(twitch_account.requests, "get", lambda *args, **kwargs: _Answer(data={"login": "somebody", "expires_in": 0}))
    started = client.post("/api/v1/sources/authentication/twitch/account/code").json()
    # The Site's own device code never reaches the UI.
    assert started["userCode"] == "ABCDEFGH" and "device" not in started.values()

    finished = client.post(f"/api/v1/sources/authentication/twitch/account/code/{started['id']}")
    assert finished.status_code == 200
    assert finished.json()["accountStatus"] == {"signedIn": True, "account": "somebody", "problem": None}
    # A code is used once.
    assert client.post(f"/api/v1/sources/authentication/twitch/account/code/{started['id']}").status_code == 410


def test_cancelling_a_sign_in_with_a_code_stops_asking_twitch(client, monkeypatch):
    from sources.ytdlp import twitch_account

    asked = []

    def post(url, data=None, **kwargs):
        asked.append(url)
        return _Answer(data={"device_code": "device", "user_code": "ABCDEFGH", "verification_uri": "https://www.twitch.tv/activate", "expires_in": 1800, "interval": 1})

    monkeypatch.setattr(twitch_account.requests, "post", post)
    started = client.post("/api/v1/sources/authentication/twitch/account/code").json()
    assert client.delete(f"/api/v1/sources/authentication/twitch/account/code/{started['id']}").status_code == 204
    assert client.post(f"/api/v1/sources/authentication/twitch/account/code/{started['id']}").status_code == 410
    assert asked == ["https://id.twitch.tv/oauth2/device"]
