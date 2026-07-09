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
    assert "ledgers/entries" in names


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
