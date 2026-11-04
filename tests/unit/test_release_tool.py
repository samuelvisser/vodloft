from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RELEASE_TOOL_PATH = REPOSITORY_ROOT / "release.py"
SPEC = importlib.util.spec_from_file_location("vodloft_release_tool", RELEASE_TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
release_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_tool
SPEC.loader.exec_module(release_tool)


def test_semantic_version_bumps():
    assert release_tool.bump_version("1.2.3", "major") == "2.0.0"
    assert release_tool.bump_version("1.2.3", "minor") == "1.3.0"
    assert release_tool.bump_version("1.2.3", "patch") == "1.2.4"


def test_distribution_names_are_normalized_for_package_tags():
    assert release_tool.normalize_distribution_name("DailyWire_API") == "dailywire-api"
    component = release_tool.Component(
        name="DailyWire_API",
        version="1.2.3",
        manifest=Path("server/example/pyproject.toml"),
        path=Path("server/example"),
    )
    assert component.tag == "dailywire-api-v1.2.3"


def test_project_version_replacement_only_changes_project_table():
    original = (
        '[tool.example]\nversion = "9.9.9"\n\n'
        '[project]\nname = "example"\nversion = "0.1.0"\n'
    )

    updated = release_tool.replace_project_version(original, "1.0.0")

    assert '[tool.example]\nversion = "9.9.9"' in updated
    assert '[project]\nname = "example"\nversion = "1.0.0"' in updated


def test_module_version_replacement_preserves_quote_style():
    assert release_tool.replace_module_version(
        "__version__ = '0.1.0'\n",
        "2.0.0",
    ) == "__version__ = '2.0.0'\n"


def test_release_container_version_tags():
    assert release_tool.container_version_tags("2.3.4") == ["2.3.4", "2.3", "2"]


def test_publish_delegates_container_tagging_to_deploy(monkeypatch):
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(release_tool, "verify_publish_state", lambda: None)
    monkeypatch.setattr(release_tool, "tags_to_publish", lambda: ([], "v2.3.4"))
    monkeypatch.setattr(release_tool, "push_release_tags", lambda *_args: None)

    def fake_run(*args: str, **_kwargs):
        calls.append(args)

    monkeypatch.setattr(release_tool, "run", fake_run)

    release_tool.publish_release(argparse.Namespace(skip_container=False, yes=True))

    assert [call for call in calls if call[0] == "./deploy.sh"] == [
        ("./deploy.sh", "--tag-level", "main", "2.3.4", "2.3", "2")
    ]


def test_application_release_tag_is_pushed_separately(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str, **_kwargs):
        calls.append(args)

    monkeypatch.setattr(release_tool, "run", fake_run)

    release_tool.push_release_tags(
        ["backend-v0.2.0", "config-v0.1.1"],
        "v1.1.0",
    )

    assert calls == [
        (
            "git",
            "push",
            "--atomic",
            "origin",
            "backend-v0.2.0",
            "config-v0.1.1",
        ),
        ("git", "push", "origin", "v1.1.0"),
    ]


def test_a_failing_command_without_captured_output_raises_a_release_error():
    import pytest

    with pytest.raises(release_tool.ReleaseError, match="exit code 3"):
        release_tool.run(sys.executable, "-c", "raise SystemExit(3)", capture_output=False)


def test_upgrade_steps_pin_the_release_image():
    steps = release_tool.render_upgrade_steps("2.3.4", "2.3.3")

    assert "ghcr.io/samuelvisser/vodloft:2.3.4" in steps
    assert "ghcr.io/samuelvisser/vodloft:2.3.3" in steps
    assert "vodloft/v2.3.4/.docker/docker-compose.yml" in steps
    assert ":latest" not in steps
    assert "$" not in steps


def test_upgrade_steps_rewrite_the_image_line_of_the_published_compose_file(tmp_path):
    steps = release_tool.render_upgrade_steps("2.3.4", "2.3.3")
    sed_command = next(line for line in steps.splitlines() if line.strip().startswith("sed -i 's#"))
    expression = sed_command.split("'")[1]
    pattern, replacement = expression.split("#")[1:3]
    compose = (REPOSITORY_ROOT / ".docker" / "docker-compose.yml").read_text()

    updated = re.sub(pattern.replace(".", r"\."), replacement, compose)

    assert "image: ghcr.io/samuelvisser/vodloft:2.3.4\n" in updated
    assert "vodloft:latest" not in updated


def test_upgrade_steps_go_back_to_the_release_before(monkeypatch):
    monkeypatch.setattr(
        release_tool,
        "version_tags",
        lambda prefix: [((0, 7, 0), "v0.7.0"), ((0, 6, 1), "v0.6.1"), ((0, 6, 0), "v0.6.0")],
    )

    assert release_tool.previous_app_version("0.7.0") == "0.6.1"
    assert release_tool.previous_app_version("0.8.0") == "0.7.0"
