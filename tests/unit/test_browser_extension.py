"""VODLoft offers its browser extension, built with the UI, as a zip to load into a browser."""
import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.api.endpoints import browser_extension_router

    app = FastAPI()
    app.include_router(browser_extension_router, prefix="/api/v1")
    with TestClient(app) as test_client:
        yield test_client


def test_the_built_extension_downloads_as_a_zip_to_load_into_a_browser(client, tmp_path, monkeypatch):
    from backend.services import browser_extension

    # The UI's build makes the extension; here a built one stands in.
    built = tmp_path / "dist-extension"
    (built / "assets").mkdir(parents=True)
    (built / "manifest.json").write_text(json.dumps({"manifest_version": 3, "background": {"service_worker": "background.js"}}))
    (built / "background.js").write_text("")
    (built / "assets" / "popup.js").write_text("")
    monkeypatch.setattr(browser_extension, "EXTENSION_DIRECTORY", built)

    downloaded = client.get("/api/v1/browser-extension")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/zip"
    assert 'filename="vodloft-browser-extension.zip"' in downloaded.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(downloaded.content))
    assert {
        "vodloft-browser-extension/manifest.json",
        "vodloft-browser-extension/background.js",
        "vodloft-browser-extension/assets/popup.js",
    } <= set(archive.namelist())
    assert json.loads(archive.read("vodloft-browser-extension/manifest.json"))["manifest_version"] == 3


def test_without_a_built_extension_the_download_says_so(client, tmp_path, monkeypatch):
    from backend.services import browser_extension

    monkeypatch.setattr(browser_extension, "EXTENSION_DIRECTORY", tmp_path / "missing")
    refused = client.get("/api/v1/browser-extension")
    assert refused.status_code == 404
    assert "Build the UI" in refused.json()["detail"]


def test_the_extension_manifest_names_what_the_build_makes():
    """The manifest the build copies names the background script and popup the extension's Vite build writes."""
    from backend.config import PROJECT_ROOT

    manifest = json.loads((PROJECT_ROOT / "ui" / "extension" / "public" / "manifest.json").read_text())
    assert manifest["manifest_version"] == 3
    assert manifest["background"]["service_worker"] == "background.js" == manifest["background"]["scripts"][0]
    assert manifest["action"]["default_popup"] == "popup.html"
    assert (PROJECT_ROOT / "ui" / "extension" / "popup.html").is_file()
    assert "downloads" in manifest["permissions"]
