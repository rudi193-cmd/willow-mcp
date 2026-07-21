"""Tests for specialist registry compile pipeline."""

import json

import pytest

from willow_mcp import registry as reg
from willow_mcp import home_init as hi


def test_load_registry_from_bundle():
    data = reg.load_registry(prefer_home=False)
    assert data.get("format") == reg.REGISTRY_FORMAT
    ids = [r["agent_id"] for r in data.get("specialists") or []]
    assert "hanuman" in ids
    assert data.get("orchestrator_seat", {}).get("agent_id") == "willow"
    orch_perms = data["orchestrator_seat"]["permissions"]
    assert "orchestrator" in orch_perms
    assert "commitment_read" in orch_perms
    assert "store_read" in orch_perms
    assert "knowledge_read" in orch_perms


def test_orchestrator_manifest_supports_session_start_tools(home):
    """session-start open ritual needs tools outside the orchestrator group alone."""
    from willow_mcp.gate import permitted

    hi.ensure_home_layout()
    reg.compile_manifests(reg.load_registry(), only_missing=False)
    for tool in ("commitment_surface", "store_list", "kb_startup_continuity"):
        assert permitted("willow", tool), f"willow manifest must permit {tool}"


def test_manifest_from_row_includes_deny_tools():
    row = {
        "agent_id": "loki",
        "role": "auditor",
        "permissions": ["knowledge_read"],
        "deny_tools": ["task_submit", "store_put"],
        "store_scope": ["loki_*"],
        "human_only": False,
    }
    manifest = reg.manifest_from_row(row)
    assert manifest["deny_tools"] == ["task_submit", "store_put"]
    assert manifest["store_scope"] == ["loki_*"]


def test_compile_manifests_only_missing(home):
    hi.ensure_home_layout()
    first = reg.compile_manifests(reg.load_registry(), only_missing=True)
    assert first["written"] == []
    assert "mcp_apps/hanuman/manifest.json" in first["skipped"]

    second = reg.compile_manifests(reg.load_registry(), only_missing=False)
    assert "mcp_apps/hanuman/manifest.json" in second["written"]

    manifest = json.loads((home / "mcp_apps" / "hanuman" / "manifest.json").read_text())
    assert manifest["permissions"] == [
        "dispatch_read",
        "dispatch_write",
        "task_queue",
        "store_read",
        "knowledge_read",
    ]
    assert "kb_promote" in manifest["deny_tools"]


def test_compile_agents_force_overwrites(home, monkeypatch):
    hi.ensure_home_layout()
    path = home / "mcp_apps" / "hanuman" / "manifest.json"
    path.write_text(json.dumps({"permissions": ["full_access"]}) + "\n")

    out = reg.compile_agents_main(force=True)
    assert "mcp_apps/hanuman/manifest.json" in out["written"]
    manifest = json.loads(path.read_text())
    assert "full_access" not in manifest["permissions"]


def test_list_specialists_sorted(home):
    rows = reg.list_specialists()
    assert rows[0]["agent_id"] == "willow"
    assert any(r["agent_id"] == "hanuman" for r in rows)


def test_get_specialist_includes_permissions(home):
    row = reg.get_specialist("loki")
    assert row["agent_id"] == "loki"
    assert "knowledge_read" in row["permissions"]
    assert "task_submit" in row["deny_tools"]


def test_read_persona_text_from_bundle(home):
    text = reg.read_persona_text("jeles")
    assert text and "Jeles" in text
