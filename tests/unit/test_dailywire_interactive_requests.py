from types import SimpleNamespace


def test_catalog_ui_read_bypasses_background_pacing(monkeypatch):
    from backend.api.endpoints.dailywire.catalog import service

    captured: dict[str, object] = {}
    catalog = object()

    class FakeAuth:
        def get_token(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def get_catalog(self):
            return catalog

    monkeypatch.setattr(service, "_catalog_cache", None)
    monkeypatch.setattr(service, "DeviceAuthClient", FakeAuth)
    monkeypatch.setattr(service, "MiddlewareClient", FakeClient)

    assert service.get_catalog() is catalog
    assert captured["request_priority"] == "interactive"


def test_a_show_looked_up_to_add_lists_with_the_accounts_level_and_skips_background_pacing(monkeypatch):
    from sources.dailywire import source
    from sources.dailywire.api.types.user_info import DwMembershipLevel

    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def get_show_page(self, *, slug):
            assert slug == "example-show"
            return SimpleNamespace(
                slug="example-show", title="Example Show", description=None, thumbnail_landscape_path=None,
                author_name="Host", author_slug="host", author_headshot_path="host.jpg", seasons=[],
                latest_season=None, probable_collection_type=SimpleNamespace(value="podcast"),
            )

    monkeypatch.setattr(source, "MiddlewareClient", FakeClient)
    monkeypatch.setattr(source, "_access_token", lambda: "token")
    monkeypatch.setattr(source, "_season_refs", lambda show: {})
    monkeypatch.setattr(source, "account_level", lambda: DwMembershipLevel.INSIDER)

    details = source.DailyWireSource().collection_details("https://www.dailywire.com/show/example-show")

    assert captured == {"access_token": "token", "request_priority": "interactive"}
    assert details.membership_level == "INSIDER"
    assert details.author_image_url == "host.jpg"
    assert details.probable_type == "podcast"

    monkeypatch.setattr(source, "account_level", lambda: DwMembershipLevel.READER)
    assert source.DailyWireSource().collection_details(
        "https://www.dailywire.com/show/example-show"
    ).membership_level == "FREE"


def test_movie_ui_read_bypasses_background_pacing(monkeypatch):
    from backend.api.endpoints.dailywire.movies import service

    captured: dict[str, object] = {}
    movie = object()

    class FakeAuth:
        def get_token(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def get_movie_page(self, slug):
            assert slug == "example-movie"
            return movie

    monkeypatch.setattr(service, "DeviceAuthClient", FakeAuth)
    monkeypatch.setattr(service, "MovieMiddlewareClient", FakeClient)
    monkeypatch.setattr(service, "_prefer_reliable_catalog_poster", lambda record: record)

    assert service.get_live_movie("example-movie") is movie
    assert captured["request_priority"] == "interactive"


def test_user_info_ui_read_bypasses_background_pacing(monkeypatch):
    from backend.api.endpoints.dailywire.user_info import service

    captured: dict[str, object] = {}
    user_info = object()

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def get_user_info(self):
            return user_info

    monkeypatch.setattr(service, "MiddlewareClient", FakeClient)

    assert service.get_user_info() is user_info
    assert captured["request_priority"] == "interactive"
