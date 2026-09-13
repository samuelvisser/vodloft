from pathlib import Path

from config import Settings, load_settings, save_settings


def test_settings_round_trip_to_explicit_path(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    settings = Settings(
        database_url="sqlite:///example.db",
        task_manager={"download_max_concurrency": 4},
        yt_dlp={"options": {"cookiesfrombrowser": ["firefox"]}},
    )
    saved = save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded == saved
    assert loaded.task_manager.download_max_concurrency == 4
    assert loaded.yt_dlp.options["cookiesfrombrowser"] == ["firefox"]
