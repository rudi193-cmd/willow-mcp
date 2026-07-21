"""Tests for B-32 trust-root hardening operator tooling."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from willow_mcp import home_init as hi
from willow_mcp import paths
from willow_mcp import trust_root_setup as trs


def test_audit_reports_forgeable_paths_on_default_home(home):
    hi.ensure_home_layout()
    audit = trs.audit_trust_root("hanuman")
    assert audit["strict_trust_root"] is False
    assert audit["hardened"] is False
    keys = {item["key"] for item in audit["forgeable"]}
    assert "lease_root" in keys


def test_audit_hardened_when_strict_and_nothing_forgeable(home, monkeypatch):
    hi.ensure_home_layout()
    monkeypatch.setenv("WILLOW_MCP_STRICT_TRUST_ROOT", "1")
    monkeypatch.setattr(trs.lease, "self_writable_trust_paths", lambda *_: [])
    monkeypatch.setattr(trs.lease, "path_is_self_writable_or_replaceable", lambda *_: False)
    audit = trs.audit_trust_root("hanuman")
    assert audit["hardened"] is True


def test_merge_strict_env_into_mcp_json(tmp_path):
    mcp_json = tmp_path / ".cursor" / "mcp.json"
    mcp_json.parent.mkdir(parents=True)
    mcp_json.write_text(
        json.dumps({"mcpServers": {"willow-mcp": {"command": "willow-mcp"}}}) + "\n",
        encoding="utf-8",
    )
    assert trs.merge_mcp_env(mcp_json, trs.mcp_env_snippet()) is True
    data = json.loads(mcp_json.read_text(encoding="utf-8"))
    assert data["mcpServers"]["willow-mcp"]["env"]["WILLOW_MCP_STRICT_TRUST_ROOT"] == "1"


def test_harden_dry_run_lists_actions(home, monkeypatch):
    hi.ensure_home_layout()
    monkeypatch.setattr(trs, "resolve_trust_owner", lambda owner: "operator")
    result = trs.harden_trust_root(owner="operator", dry_run=True)
    assert result["filesystem"]["dry_run"] is True
    assert any("chown -R operator:operator" in action for action in result["filesystem"]["actions"])
    assert any("find " in action and "chmod 644" in action for action in result["filesystem"]["actions"])


def test_chmod_tree_uses_privileged_find(home, monkeypatch):
    hi.ensure_home_layout()
    calls: list[list[str]] = []

    def _capture(argv, *, dry_run):
        calls.append(list(argv))

    monkeypatch.setattr(trs, "_run_privileged", _capture)
    trs._chmod_tree(paths.mcp_apps_root(), dir_mode=0o755, file_mode=0o644)
    assert any(cmd[:4] == ["find", str(paths.mcp_apps_root()), "-type", "f"] for cmd in calls)
    assert any(cmd[:4] == ["find", str(paths.mcp_apps_root()), "-type", "d"] for cmd in calls)


def test_resolve_trust_owner_requires_existing_user(monkeypatch):
    def _missing(_name):
        raise KeyError("missing")

    monkeypatch.setattr(trs.pwd, "getpwnam", _missing)
    with pytest.raises(ValueError, match="does not exist"):
        trs.resolve_trust_owner("nobody-here")


def test_resolve_trust_owner_accepts_existing_user(monkeypatch):
    monkeypatch.setattr(trs.pwd, "getpwnam", lambda name: object())
    assert trs.resolve_trust_owner("operator") == "operator"


def test_trust_root_directories_include_mcp_apps_and_config(home):
    hi.ensure_home_layout()
    roots = {p.name for p in trs.trust_root_directories()}
    assert "mcp_apps" in roots
    assert "config" in roots
    assert paths.willow_home().name not in {p.name for p in trs.trust_root_directories() if p == paths.willow_home()}


def test_trust_root_directories_skip_home_root_when_legacy_policy_files_exist(home):
    hi.ensure_home_layout()
    legacy = paths.consent_legacy_path()
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"consent": {"internet": false, "cloud_llm": false, "lan": false}}\n', encoding="utf-8")
    roots = trs.trust_root_directories()
    assert paths.willow_home() not in roots
    assert legacy in trs.trust_policy_files()


def test_runtime_writable_includes_store_not_config(home):
    hi.ensure_home_layout()
    names = {p.name for p in trs.runtime_writable_directories()}
    assert "store" in names
    assert "config" not in names
    assert "mcp_apps" not in names


def test_repair_runtime_dry_run_targets_store(home, monkeypatch):
    hi.ensure_home_layout()
    monkeypatch.setattr(trs, "resolve_runtime_user", lambda _user: "runtime")
    result = trs.repair_runtime_permissions(dry_run=True)
    assert result["runtime_user"] == "runtime"
    assert any("store" in target for target in result["targets"])
    assert any("chown -R runtime:runtime" in action for action in result["actions"])
