"""Tests for gate.py — manifest-based per-tool ACL. Previously untested (L-TEST-01)."""

import json

import pytest
from willow_mcp import gate


@pytest.fixture
def apps_root(tmp_path, monkeypatch):
    root = tmp_path / "mcp_apps"
    root.mkdir()
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(root))
    return root


def _write_manifest(apps_root, app_id, permissions):
    app_dir = apps_root / app_id
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "manifest.json").write_text(json.dumps({"permissions": permissions}))


def test_authorized_false_without_manifest(apps_root):
    assert gate.authorized("nobody") is False


def test_authorized_true_with_manifest(apps_root):
    _write_manifest(apps_root, "testapp", ["store_read"])
    assert gate.authorized("testapp") is True


def test_permitted_denies_missing_manifest(apps_root):
    assert gate.permitted("nobody", "store_get") is False


def test_permitted_denies_empty_permissions(apps_root):
    _write_manifest(apps_root, "emptyperm", [])
    assert gate.permitted("emptyperm", "store_get") is False


def test_permitted_expands_group(apps_root):
    _write_manifest(apps_root, "reader", ["store_read"])
    assert gate.permitted("reader", "store_get") is True
    assert gate.permitted("reader", "store_search") is True
    assert gate.permitted("reader", "store_put") is False  # write not in store_read


def test_permitted_literal_tool_name(apps_root):
    _write_manifest(apps_root, "narrow", ["fleet_status"])
    assert gate.permitted("narrow", "fleet_status") is True
    assert gate.permitted("narrow", "fleet_health") is False


def test_permitted_denies_invalid_app_id(apps_root):
    # Path-traversal / illegal characters must be rejected before any
    # manifest lookup, regardless of whether a matching file happens to exist.
    assert gate.permitted("../../etc/passwd", "store_get") is False
    assert gate.permitted("", "store_get") is False


def test_permitted_full_access_group(apps_root):
    _write_manifest(apps_root, "admin", ["full_access"])
    for tool in ("store_put", "knowledge_ingest", "task_submit", "fleet_health"):
        assert gate.permitted("admin", tool) is True
