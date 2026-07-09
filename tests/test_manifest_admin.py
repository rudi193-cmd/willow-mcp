"""Tests for manifest_admin.py — the local-CLI-only permission toggle backing
`willow-mcp allow-permission` / `deny-permission`."""
import json

import pytest

from willow_mcp import manifest_admin


@pytest.fixture
def apps_root(tmp_path, monkeypatch):
    root = tmp_path / "mcp_apps"
    root.mkdir()
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(root))
    return root


def test_set_permission_creates_manifest_when_absent(apps_root):
    manifest = manifest_admin.set_permission("newapp", "store_read", True)
    assert manifest["permissions"] == ["store_read"]
    on_disk = json.loads((apps_root / "newapp" / "manifest.json").read_text())
    assert on_disk["permissions"] == ["store_read"]


def test_set_permission_is_additive_and_dedupes(apps_root):
    manifest_admin.set_permission("app", "store_read", True)
    manifest = manifest_admin.set_permission("app", "store_read", True)
    assert manifest["permissions"] == ["store_read"]  # no duplicate


def test_set_permission_revokes(apps_root):
    manifest_admin.set_permission("app", "store_read", True)
    manifest_admin.set_permission("app", "task_net", True)
    manifest = manifest_admin.set_permission("app", "store_read", False)
    assert manifest["permissions"] == ["task_net"]


def test_set_permission_revoke_on_absent_manifest_writes_nothing(apps_root):
    """A revoke that changes nothing must not materialize a manifest: an empty
    manifest reads as `store_scope` unrestricted, while no manifest at all
    reads as deny-all (gate.py) — so this no-op must not silently widen access."""
    manifest = manifest_admin.set_permission("ghost", "store_read", False)
    assert manifest["permissions"] == []
    assert not (apps_root / "ghost" / "manifest.json").exists()


def test_set_permission_rejects_unknown_name(apps_root):
    with pytest.raises(ValueError, match="unknown permission"):
        manifest_admin.set_permission("app", "not_a_real_group", True)


def test_set_permission_preserves_other_manifest_fields(apps_root):
    app_dir = apps_root / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["store_read"], "store_scope": ["app_*"]})
    )
    manifest = manifest_admin.set_permission("app", "task_net", True)
    assert manifest["store_scope"] == ["app_*"]
    assert set(manifest["permissions"]) == {"store_read", "task_net"}


def test_set_permission_rejects_invalid_app_id(apps_root):
    with pytest.raises(ValueError):
        manifest_admin.set_permission("../escape", "store_read", True)
