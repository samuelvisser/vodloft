from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.settings.cron_validation import (
    CronExpressionError,
    minimum_cron_interval_seconds,
    validate_cron_expression,
)
from config.settings.settings import AppSettings


def _settings_document() -> dict:
    return AppSettings(timezone="UTC").model_dump(mode="python")


def _validate_with_cron(path: tuple[str, str], expression: str, *, slow_ms: int = 120_000):
    values = _settings_document()
    values["dw_timeout"]["min_slow_request_ms"] = slow_ms
    values[path[0]][path[1]] = expression
    return AppSettings.model_validate(values)


@pytest.mark.parametrize(
    ("expression", "minimum_seconds"),
    [
        ("* * * * *", 60),
        ("0,1 0 * * *", 60),
        ("5/10 * * * *", 10 * 60),
        ("*/2 * * * *", 120),
        ("0 */2 * * *", 2 * 60 * 60),
        ("0 0 * * mon", 7 * 24 * 60 * 60),
        ("0 0 last * *", 28 * 24 * 60 * 60),
        ("0 0 29 feb *", 1461 * 24 * 60 * 60),
    ],
)
def test_static_cron_analyzer_finds_exact_minimum(expression, minimum_seconds):
    assert minimum_cron_interval_seconds(expression) == minimum_seconds


@pytest.mark.parametrize(
    "expression",
    [
        "banana * * * *",
        "* * * *",
        "60 * * * *",
        "*/0 * * * *",
        "0 0 */31 * *",
        "0 0 1 jan/2 *",
        "0 0 * * mon/2",
        "0 0 1 jan-3 *",
        "0 0 32 * *",
    ],
)
def test_static_cron_analyzer_rejects_invalid_expressions(expression):
    with pytest.raises(CronExpressionError):
        validate_cron_expression(expression)


def test_default_monitor_interval_matches_slow_request_delay():
    settings = AppSettings(timezone="UTC")

    assert settings.new_episode_schedule.monitor_pending_episode_cron == "*/2 * * * *"
    assert settings.dw_timeout.min_slow_request_ms == 120_000


@pytest.mark.parametrize(
    "path",
    [
        ("new_episode_schedule", "find_episodes_cron"),
        ("new_episode_schedule", "monitor_pending_episode_cron"),
        ("new_episode_schedule", "monitor_no_usable_media_episode_cron"),
        ("download_settings", "verify_downloads_cron"),
        ("file_watcher", "scan_cron"),
    ],
)
def test_all_worker_crons_reject_intervals_shorter_than_slow_delay(path):
    with pytest.raises(ValidationError, match="requires at least 120 seconds"):
        _validate_with_cron(path, "* * * * *")


def test_disabled_worker_cron_skips_minimum_interval_validation():
    values = _settings_document()
    values["new_episode_schedule"]["find_episodes_cron_enabled"] = False
    values["new_episode_schedule"]["find_episodes_cron"] = "* * * * *"

    settings = AppSettings.model_validate(values)

    assert settings.new_episode_schedule.find_episodes_cron_enabled is False


def test_worker_cron_accepts_interval_equal_to_slow_delay():
    settings = _validate_with_cron(
        ("new_episode_schedule", "monitor_pending_episode_cron"),
        "*/2 * * * *",
    )

    assert settings.new_episode_schedule.monitor_pending_episode_cron == "*/2 * * * *"


def test_worker_cron_uses_configured_slow_delay():
    with pytest.raises(ValidationError, match="requires at least 180 seconds"):
        _validate_with_cron(
            ("new_episode_schedule", "monitor_pending_episode_cron"),
            "*/2 * * * *",
            slow_ms=180_000,
        )


def test_worker_cron_validation_handles_non_uniform_schedules():
    with pytest.raises(ValidationError, match="requires at least 120 seconds"):
        _validate_with_cron(
            ("new_episode_schedule", "monitor_pending_episode_cron"),
            "0,1 0 * * *",
        )


def test_settings_api_rejects_too_fast_worker_cron_on_the_cron_field():
    from backend.api.models.settings import SettingsAPIUpdate, SettingsValues

    values = SettingsValues.from_app_settings(AppSettings(timezone="UTC")).model_dump(
        by_alias=True,
        mode="json",
    )
    values["newEpisodeSchedule"]["monitorPendingEpisodeCron"] = "* * * * *"

    with pytest.raises(ValidationError, match="requires at least 120 seconds") as exc_info:
        SettingsAPIUpdate.model_validate({
            "values": values,
            "changedFields": ["newEpisodeSchedule.monitorPendingEpisodeCron"],
        })

    matching_errors = [
        error
        for error in exc_info.value.errors()
        if error["loc"] == (
            "values",
            "newEpisodeSchedule",
            "monitorPendingEpisodeCron",
        )
    ]
    assert len(matching_errors) == 1
    assert matching_errors[0]["type"] == "worker_cron_interval_too_short"


def test_settings_api_revalidates_crons_when_slow_delay_is_increased():
    from backend.api.models.settings import SettingsAPIUpdate, SettingsValues

    values = SettingsValues.from_app_settings(AppSettings(timezone="UTC")).model_dump(
        by_alias=True,
        mode="json",
    )
    values["dwTimeout"]["minSlowRequestMs"] = 15 * 60 * 1000

    with pytest.raises(ValidationError, match="requires at least 900 seconds"):
        SettingsAPIUpdate.model_validate({
            "values": values,
            "changedFields": ["dwTimeout.minSlowRequestMs"],
        })
