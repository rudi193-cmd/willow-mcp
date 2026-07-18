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


def test_valid_app_id():
    assert gate.valid_app_id("sandbox") is True
    assert gate.valid_app_id("a_b-c123") is True
    assert gate.valid_app_id("bad/../app") is False      # path separators
    assert gate.valid_app_id("has.dots") is False
    assert gate.valid_app_id("") is False
    assert gate.valid_app_id("x" * 65) is False          # over 64 chars


def test_permitted_full_access_group(apps_root):
    _write_manifest(apps_root, "admin", ["full_access"])
    for tool in ("store_put", "knowledge_ingest", "task_submit", "fleet_health"):
        assert gate.permitted("admin", tool) is True


def test_permitted_deny_tools_overlay(apps_root):
    app_dir = apps_root / "deny"
    app_dir.mkdir()
    (app_dir / "manifest.json").write_text(
        json.dumps({
            "permissions": ["full_access"],
            "deny_tools": ["task_submit", "knowledge_ingest"],
        })
    )
    assert gate.permitted("deny", "store_get") is True
    assert gate.permitted("deny", "task_submit") is False
    assert gate.permitted("deny", "knowledge_ingest") is False


def test_permitted_malformed_deny_tools_fails_closed(apps_root):
    app_dir = apps_root / "badden"
    app_dir.mkdir()
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["store_read"], "deny_tools": "not-a-list"})
    )
    assert gate.permitted("badden", "store_get") is False


# ── store_scope / collection isolation (B-24 / L-ISO-01) ────────────────────

def test_store_scope_none_when_unset(apps_root):
    _write_manifest(apps_root, "unscoped", ["full_access"])
    assert gate.store_scope("unscoped") is None


def test_store_scope_explicit_null_is_unrestricted(apps_root):
    # An explicit `null` declares "no policy", same as omitting the field.
    app_dir = apps_root / "nulled"
    app_dir.mkdir()
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["full_access"], "store_scope": None})
    )
    assert gate.store_scope("nulled") is None


def test_store_scope_returns_manifest_list(apps_root):
    _write_manifest(apps_root, "scoped", ["full_access"], store_scope=["myapp_*", "shared_notes"])
    assert gate.store_scope("scoped") == ["myapp_*", "shared_notes"]


# ── fail-closed: a scope that cannot be read is not consent ──────────────────

def test_store_scope_no_manifest_denies_all(apps_root):
    # gate.py fails closed on a missing manifest everywhere else; scope too.
    assert gate.store_scope("ghost") == []
    assert gate.collection_permitted("ghost", "agents") is False


def test_store_scope_invalid_app_id_denies_all(apps_root):
    assert gate.store_scope("../../etc") == []
    assert gate.collection_permitted("../../etc", "agents") is False


def test_store_scope_malformed_denies_all(apps_root):
    # `"store_scope": "myapp_*"` — a string, not a list — is the obvious typo
    # for this field. Reading it as "unrestricted" would hand full store access
    # to an operator who believes the app is confined. Deny, and break loudly.
    app_dir = apps_root / "bad"
    app_dir.mkdir()
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["full_access"], "store_scope": "not-a-list"})
    )
    assert gate.store_scope("bad") == []
    assert gate.collection_permitted("bad", "myapp_notes") is False
    assert gate.collection_permitted("bad", "agents") is False


def test_store_scope_non_string_entries_deny_all(apps_root):
    app_dir = apps_root / "mixed"
    app_dir.mkdir()
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["full_access"], "store_scope": ["myapp_*", 7]})
    )
    assert gate.store_scope("mixed") == []
    assert gate.collection_permitted("mixed", "myapp_notes") is False


def test_store_scope_unreadable_manifest_denies_all(apps_root):
    app_dir = apps_root / "corrupt"
    app_dir.mkdir()
    (app_dir / "manifest.json").write_text("{ this is not json")
    assert gate.store_scope("corrupt") == []
    assert gate.collection_permitted("corrupt", "agents") is False


def test_store_scope_denied_list_is_not_shared_mutable_state(apps_root):
    a = gate.store_scope("ghost")
    a.append("agents")
    assert gate.store_scope("ghost") == []


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


# ── gap backlog permission groups ────────────────────────────────────────────

def test_gap_read_expands_to_gap_list_only(apps_root):
    _write_manifest(apps_root, "gap_reader", ["gap_read"])
    assert gate.permitted("gap_reader", "gap_list") is True
    assert gate.permitted("gap_reader", "gap_log") is False
    assert gate.permitted("gap_reader", "gap_promote") is False


def test_gap_write_expands_to_log_and_resolve_not_promote(apps_root):
    _write_manifest(apps_root, "gap_writer", ["gap_write"])
    assert gate.permitted("gap_writer", "gap_log") is True
    assert gate.permitted("gap_writer", "gap_resolve") is True
    assert gate.permitted("gap_writer", "gap_promote") is False


def test_gap_promote_is_its_own_group(apps_root):
    # Landing a gap as trusted knowledge is gated separately from gap_write,
    # same reasoning as schema_admin vs knowledge_write.
    _write_manifest(apps_root, "gap_promoter", ["gap_promote"])
    assert gate.permitted("gap_promoter", "gap_promote") is True
    assert gate.permitted("gap_promoter", "gap_log") is False


def test_gap_tools_included_in_full_access(apps_root):
    _write_manifest(apps_root, "admin", ["full_access"])
    for tool in ("gap_log", "gap_list", "gap_resolve", "gap_promote"):
        assert gate.permitted("admin", tool) is True


# ── egress_secret_exempt (per-manifest, per-tool redaction carve-out) ────────

def _write_raw_manifest(apps_root, app_id, manifest):
    app_dir = apps_root / app_id
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "manifest.json").write_text(json.dumps(manifest))


def test_egress_exempt_true_when_tool_listed(apps_root):
    _write_raw_manifest(apps_root, "oauthapp",
                        {"permissions": ["full_access"],
                         "egress_secret_exempt": ["integration_call", "store_get"]})
    assert gate.egress_secret_exempt("oauthapp", "integration_call") is True
    assert gate.egress_secret_exempt("oauthapp", "store_get") is True


def test_egress_exempt_false_for_unlisted_tool(apps_root):
    _write_raw_manifest(apps_root, "oauthapp",
                        {"permissions": ["full_access"],
                         "egress_secret_exempt": ["integration_call"]})
    assert gate.egress_secret_exempt("oauthapp", "store_get") is False


def test_egress_exempt_false_without_field(apps_root):
    _write_manifest(apps_root, "plainapp", ["full_access"])
    assert gate.egress_secret_exempt("plainapp", "integration_call") is False


def test_egress_exempt_fails_closed_without_manifest(apps_root):
    assert gate.egress_secret_exempt("nobody", "integration_call") is False


def test_egress_exempt_fails_closed_on_malformed_field(apps_root):
    # a bare string where a list belongs (the obvious typo) must exempt NOTHING
    _write_raw_manifest(apps_root, "typoapp",
                        {"permissions": ["full_access"],
                         "egress_secret_exempt": "integration_call"})
    assert gate.egress_secret_exempt("typoapp", "integration_call") is False


def test_egress_exempt_fails_closed_on_invalid_app_id(apps_root):
    assert gate.egress_secret_exempt("../etc", "integration_call") is False
