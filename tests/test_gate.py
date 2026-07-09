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


def _write_manifest(apps_root, app_id, permissions, store_scope=None):
    app_dir = apps_root / app_id
    app_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"permissions": permissions}
    if store_scope is not None:
        manifest["store_scope"] = store_scope
    (app_dir / "manifest.json").write_text(json.dumps(manifest))


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


# ── store_scope / collection isolation (B-24 / L-ISO-01) ────────────────────

def test_store_scope_none_when_unset(apps_root):
    _write_manifest(apps_root, "unscoped", ["full_access"])
    assert gate.store_scope("unscoped") is None


def test_store_scope_none_when_no_manifest(apps_root):
    assert gate.store_scope("ghost") is None


def test_store_scope_returns_manifest_list(apps_root):
    _write_manifest(apps_root, "scoped", ["full_access"], store_scope=["myapp_*", "shared_notes"])
    assert gate.store_scope("scoped") == ["myapp_*", "shared_notes"]


def test_store_scope_malformed_treated_as_unrestricted(apps_root):
    # A non-list or non-string-list store_scope is a manifest authoring bug,
    # not a caller-triggerable error — fail open to "unrestricted" (today's
    # default) rather than let a typo silently deny everything, but log it.
    app_dir = apps_root / "bad"
    app_dir.mkdir()
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["full_access"], "store_scope": "not-a-list"})
    )
    assert gate.store_scope("bad") is None


def test_collection_permitted_unrestricted_when_no_scope(apps_root):
    _write_manifest(apps_root, "unscoped", ["full_access"])
    assert gate.collection_permitted("unscoped", "anything_at_all") is True


def test_collection_permitted_exact_match(apps_root):
    _write_manifest(apps_root, "scoped", ["full_access"], store_scope=["mcp_smoke_test"])
    assert gate.collection_permitted("scoped", "mcp_smoke_test") is True
    assert gate.collection_permitted("scoped", "agents") is False


def test_collection_permitted_prefix_wildcard(apps_root):
    _write_manifest(apps_root, "scoped", ["full_access"], store_scope=["myapp_*"])
    assert gate.collection_permitted("scoped", "myapp_notes") is True
    assert gate.collection_permitted("scoped", "myapp_") is True
    assert gate.collection_permitted("scoped", "otherapp_notes") is False
    assert gate.collection_permitted("scoped", "myap") is False


def test_collection_permitted_empty_scope_denies_all(apps_root):
    _write_manifest(apps_root, "locked", ["full_access"], store_scope=[])
    assert gate.collection_permitted("locked", "anything") is False
