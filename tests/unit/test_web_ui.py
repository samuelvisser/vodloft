"""The backend serves the built UI itself when VL_UI_DIRECTORY names it, as the Debian package does."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.web_ui import add_web_ui


@pytest.fixture
def client(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>VODLoft</html>")
    (tmp_path / "assets" / "app-1234.js").write_text("console.log(1)")
    (tmp_path / "sw.js").write_text("self")
    (tmp_path / "manifest.webmanifest").write_text("{}")
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    add_web_ui(app, tmp_path)
    return TestClient(app)


def test_pages_of_the_app_get_its_shell_and_routes_keep_theirs(client):
    page = client.get("/collections/12")
    assert page.status_code == 200
    assert page.text == "<html>VODLoft</html>"
    assert page.headers["cache-control"] == "no-cache"
    assert client.get("/").text == "<html>VODLoft</html>"
    assert client.get("/api/health").json() == {"status": "ok"}


def test_backend_paths_and_missing_assets_are_not_pages(client):
    for path in ("/api/missing", "/feeds/x/feed.xml", "/iptv/x", "/webdav/x", "/assets/gone-1.js"):
        assert client.get(path).status_code == 404, path


def test_files_keep_the_caching_nginx_gives_them(client):
    asset = client.get("/assets/app-1234.js")
    assert asset.text == "console.log(1)"
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/sw.js").headers["cache-control"] == "no-store"
    manifest = client.get("/manifest.webmanifest")
    assert manifest.headers["content-type"].startswith("application/manifest+json")


def test_the_ui_finds_the_api_beside_it(client):
    config = client.get("/config.json")
    assert config.json() == {"API_URL": "/api"}
    assert config.headers["cache-control"] == "no-store"


def test_no_file_outside_the_ui_directory_is_served(client, tmp_path):
    (tmp_path.parent / "secret.txt").write_text("secret")
    response = client.get("/..%2Fsecret.txt")
    assert "secret" not in response.text
