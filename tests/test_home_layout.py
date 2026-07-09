"""Tests for locked $WILLOW_HOME product layout."""

import json

import pytest

from willow_mcp import paths
from willow_mcp import home_init as hi


# home fixture from tests/conftest.py


def test_all_layout_dirs_under_home(home):
    names = {p.relative_to(home).as_posix() for p in paths.all_layout_dirs()}
    assert "config" in names
    assert "dispatch" in names
    assert "mcp_apps" in names
    assert "personas" in names
    assert "seeds" in names


def test_home_init_writes_exposure_json(home):
    hi.ensure_home_layout()
    assert paths.exposure_config_path().is_file()


def test_ensure_home_layout_idempotent(home):
    first = hi.ensure_home_layout()
    second = hi.ensure_home_layout()
    assert first["layout_version"] == paths.LAYOUT_VERSION
    assert paths.layout_version_path().read_text().strip() == str(paths.LAYOUT_VERSION)
    assert paths.config_dir().is_dir()
    assert paths.settings_global_path().is_file()
    assert paths.agent_roster_path().is_file()
    assert not second["dirs_created"]
    assert not second["config_created"]


def test_bundle_seeds_copied_once(home):
    hi.ensure_home_layout()
    assert (paths.templates_dir() / "ASSIGNMENT.template.md").is_file()
    assert (paths.skills_dir() / "session-start.md").is_file()
    assert (paths.hooks_dir() / "pre_tool_use.py").is_file()
    roster = json.loads(paths.agent_roster_path().read_text())
    assert any(a["id"] == "jeles" and a["role"] == "librarian" for a in roster["agents"])


def test_registry_materialized_on_init(home):
    result = hi.ensure_home_layout()
    assert paths.specialists_config_path().is_file()
    assert (paths.personas_dir() / "hanuman.md").is_file()
    assert (paths.personas_dir() / "willow.md").is_file()
    assert (paths.seeds_dir() / "agent-seed-template.json").is_file()
    assert (paths.mcp_app_dir("hanuman") / "manifest.json").is_file()
    assert (paths.mcp_app_dir("willow") / "manifest.json").is_file()

    hanuman = json.loads((paths.mcp_app_dir("hanuman") / "manifest.json").read_text())
    assert hanuman["app_id"] == "hanuman"
    assert "task_queue" in hanuman["permissions"]
    assert "kb_promote" in hanuman.get("deny_tools", [])

    registry = result.get("registry") or {}
    assert registry.get("manifests_created") or paths.mcp_app_dir("loki").joinpath("manifest.json").is_file()

    second = hi.ensure_home_layout()
    assert not second["registry"]["personas_copied"]
    assert not second["registry"]["manifests_created"]
