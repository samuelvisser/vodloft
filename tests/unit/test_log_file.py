from __future__ import annotations

import logging

import pytest

from config import AppSettings
from config.settings.submodels import LogFileSettings


@pytest.fixture
def log_settings(tmp_path, monkeypatch):
    from backend import log_file

    monkeypatch.setenv("VL_CONFIG_FILE", str(tmp_path / "config.yml"))
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.DEBUG)

    def settings(**log_file_options) -> AppSettings:
        return AppSettings.model_construct(
            log_level=log_file_options.pop("log_level", "INFO"),
            log_file=LogFileSettings(**log_file_options),
        )

    yield settings
    log_file.configure_log_file(settings(enabled=False))
    root.setLevel(previous_level)


def test_the_log_file_follows_the_log_level_and_stops_when_turned_off(log_settings, tmp_path):
    from backend.log_file import configure_log_file, log_file_path

    configure_log_file(log_settings(enabled=True, log_level="INFO"))
    test_logger = logging.getLogger("vodloft.test")
    test_logger.debug("hidden detail")
    test_logger.info("visible line")
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", "/api/pull", "1.1", 200)
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", "/api/logs", "1.1", 200)

    configure_log_file(log_settings(enabled=True, log_level="DEBUG"))
    test_logger.debug("debug after the change")

    configure_log_file(log_settings(enabled=False))
    test_logger.info("after turning it off")

    path = log_file_path()
    assert path == tmp_path / "logs" / "vodloft.log"
    text = path.read_text(encoding="utf-8")
    assert "INFO     vodloft.test: visible line" in text
    assert "hidden detail" not in text
    assert "/api/pull" in text
    assert "/api/logs" not in text
    assert "debug after the change" in text
    assert "after turning it off" not in text
    assert text.count("visible line") == 1


def test_the_log_file_starts_a_new_part_at_its_size_limit(log_settings):
    from backend.log_file import configure_log_file, log_file_path

    configure_log_file(log_settings(enabled=True, max_megabytes=1, kept_files=2))
    line = "x" * 1000
    for _ in range(3500):
        logging.getLogger("vodloft.test").info(line)

    folder = log_file_path().parent
    assert sorted(path.name for path in folder.iterdir()) == ["vodloft.log", "vodloft.log.1", "vodloft.log.2"]
    assert all(path.stat().st_size <= 1024 * 1024 for path in folder.iterdir())
