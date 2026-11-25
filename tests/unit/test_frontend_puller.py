from types import SimpleNamespace

from backend.api.endpoints.puller import service
from backend.security.access import Access


def test_frontend_pull_includes_application_version(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(app_version="9.8.7", build_id="20261119112400"),
    )
    monkeypatch.setattr(service, "list_operations", lambda _access, **_kwargs: [])

    response = service.get_frontend_pull(Access.full())

    assert response.app_version == "9.8.7"
    assert response.model_dump(by_alias=True)["appVersion"] == "9.8.7"
    assert response.model_dump(by_alias=True)["buildId"] == "20261119112400"
