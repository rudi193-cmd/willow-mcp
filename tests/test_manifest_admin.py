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


def test_set_permission_resigns_when_pgp_enforced(apps_root, monkeypatch):
    """Rewriting a manifest invalidates its detached signature, and an unsigned
    manifest is denied everywhere — so the edit path must re-sign, or the
    operator's own supported command silently revokes the app's whole gate."""
    signed: list = []
    monkeypatch.setattr(manifest_admin.pgp, "pgp_enabled", lambda: True)
    monkeypatch.setattr(
        manifest_admin.pgp, "sign_detached",
        lambda p: (signed.append(p) or (True, str(p) + ".sig")),
    )
    manifest_admin.set_permission("app", "store_read", True)
    assert [p.name for p in signed] == ["manifest.json"]


def test_set_permission_rolls_back_when_resigning_fails(apps_root, monkeypatch):
    """A half-applied change that leaves an unsigned manifest is worse than no
    change: the app loses every tool it already had. Restore and raise."""
    manifest_admin.set_permission("app", "store_read", True)
    before = (apps_root / "app" / "manifest.json").read_text()

    monkeypatch.setattr(manifest_admin.pgp, "pgp_enabled", lambda: True)
    monkeypatch.setattr(
        manifest_admin.pgp, "sign_detached", lambda p: (False, "gpg not found on PATH"),
    )
    with pytest.raises(RuntimeError, match="rolled back"):
        manifest_admin.set_permission("app", "task_net", True)

    assert (apps_root / "app" / "manifest.json").read_text() == before


def test_set_permission_rollback_removes_a_manifest_it_created(apps_root, monkeypatch):
    """First-permission case: there is no previous content to restore, so the
    file the failed call materialized must be removed, not left unsigned."""
    monkeypatch.setattr(manifest_admin.pgp, "pgp_enabled", lambda: True)
    monkeypatch.setattr(
        manifest_admin.pgp, "sign_detached", lambda p: (False, "gpg-agent unreachable"),
    )
    with pytest.raises(RuntimeError, match="rolled back"):
        manifest_admin.set_permission("fresh", "store_read", True)

    assert not (apps_root / "fresh" / "manifest.json").exists()


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


def test_set_permission_is_idempotent_under_pgp_enforcement(apps_root, monkeypatch):
    """Re-granting a permission the app already has must stay a no-op.

    `allow-permission` is the operator's supported edit path and runbooks re-run
    it defensively. Before the guard covered the `existed and not changed` case,
    a re-grant fell through to rewrite-and-re-sign: identical content, the valid
    signature it already had discarded, gpg invoked — and on a host where signing
    fails (no agent, key on another machine) the call *raised* for a change that
    changed nothing. Rollback kept the file correct, so the damage was the
    exception, not the data; an idempotent command that throws on the second run
    is still broken.
    """
    manifest_admin.set_permission("app", "store_read", True)
    path = apps_root / "app" / "manifest.json"
    before = path.read_text()

    calls: list = []
    monkeypatch.setattr(manifest_admin.pgp, "pgp_enabled", lambda: True)
    monkeypatch.setattr(
        manifest_admin.pgp, "sign_detached",
        lambda p: (calls.append(p) or (False, "gpg-agent unreachable")),
    )

    manifest_admin.set_permission("app", "store_read", True)   # must not raise
    assert calls == [], "a no-op re-grant must not reach the signer"
    assert path.read_text() == before

    # A revoke of something not held is the same no-op, from the other side.
    manifest_admin.set_permission("app", "task_net", False)
    assert calls == []
    assert path.read_text() == before
