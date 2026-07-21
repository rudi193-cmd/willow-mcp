import json
from pathlib import Path

from willow_mcp.mcp_projects import (
    audit_all,
    audit_project,
    ensure_registry,
    load_registry,
    render_project_mcp,
    sync_project,
)
from willow_mcp.project_wiring import expand_home, render_claude_permissions


def test_expand_home():
    home = str(Path.home())
    assert expand_home("{{HOME}}/github/foo") == f"{home}/github/foo"


def test_render_project_mcp_willow_mcp_charter(tmp_path, monkeypatch):
    wh = tmp_path / ".willow"
    monkeypatch.setenv("WILLOW_HOME", str(wh))
    monkeypatch.delenv("WILLOW_STORE_ROOT", raising=False)

    entry = {
        "path": str(tmp_path / "willow-charter"),
        "agent": "willow",
        "servers": ["willow-mcp", "codebase-memory-mcp"],
        "env": {
            "WILLOW_PROJECT_ROOT": str(tmp_path / "willow-charter"),
        },
    }
    payload = render_project_mcp("willow", entry)
    names = list(payload["mcpServers"])
    assert names[0] == "willow-mcp"
    wm = payload["mcpServers"]["willow-mcp"]
    assert wm["args"] == ["-m", "willow_mcp"]
    assert wm["env"]["WILLOW_APP_ID"] == "willow"
    assert wm["env"]["WILLOW_HUMAN_ORCHESTRATOR"] == "1"
    assert wm["env"]["WILLOW_STORE_ROOT"] == str((wh / "store").resolve())


def test_render_claude_permissions_willow_mcp():
    perms = render_claude_permissions(["willow-mcp", "codebase-memory-mcp"])
    assert "mcp__willow-mcp__*" in perms["permissions"]["allow"]
    assert "mcp__willow__app_uninstall" not in perms["permissions"]["deny"]


def test_sync_and_audit_roundtrip(tmp_path, monkeypatch):
    wh = tmp_path / ".willow"
    monkeypatch.setenv("WILLOW_HOME", str(wh))

    proj = tmp_path / "dispatches"
    proj.mkdir()
    (proj / ".cursor").mkdir(parents=True, exist_ok=True)

    registry = {
        "version": 1,
        "projects": {
            "test-proj": {
                "path": str(proj),
                "agent": "willow",
                "servers": ["willow-mcp"],
                "ides": ["cursor", "claude"],
                "wiring": {
                    "hooks": True,
                    "active_agent": True,
                    "claude_settings": "project",
                },
            }
        },
    }
    reg_path = wh / "mcp" / "projects.json"
    reg_path.parent.mkdir(parents=True)
    reg_path.write_text(json.dumps(registry), encoding="utf-8")

    entry = registry["projects"]["test-proj"]
    sync_project("test-proj", entry, dry_run=False)
    assert (wh / "mcp" / "test-proj.mcp.json").is_file()
    assert (proj / ".cursor" / "mcp.json").is_file()
    assert (proj / ".mcp.json").is_file()
    assert (proj / ".claude" / "settings.local.json").is_file()
    assert (proj / ".cursor" / "hooks.json").is_file()
    assert (proj / ".willow" / "active-agent").read_text().strip() == "willow"

    issues = audit_project("test-proj", entry)
    assert issues == [], f"expected no drift, got {issues}"


def test_render_project_mcp_with_env_overrides(tmp_path, monkeypatch):
    wh = tmp_path / ".willow"
    monkeypatch.setenv("WILLOW_HOME", str(wh))

    custom_store = tmp_path / "store" / ".willow" / "store"
    entry = {
        "path": str(tmp_path / "store"),
        "agent": "hanuman",
        "servers": ["willow-mcp"],
        "env": {"WILLOW_STORE_ROOT": str(custom_store)},
    }
    payload = render_project_mcp("hanuman-seat", entry)
    assert payload["mcpServers"]["willow-mcp"]["env"]["WILLOW_APP_ID"] == "hanuman"
    assert payload["mcpServers"]["willow-mcp"]["env"]["WILLOW_STORE_ROOT"] == str(
        custom_store.resolve()
    )


def test_render_project_mcp_ignores_charter_local_store(tmp_path, monkeypatch):
    wh = tmp_path / ".willow"
    monkeypatch.setenv("WILLOW_HOME", str(wh))
    monkeypatch.delenv("WILLOW_STORE_ROOT", raising=False)

    entry = {
        "path": str(tmp_path / "willow-charter"),
        "agent": "willow",
        "servers": ["willow-mcp"],
        "env": {
            "WILLOW_STORE_ROOT": str(tmp_path / "willow-charter" / ".willow" / "store"),
        },
    }
    payload = render_project_mcp("willow", entry)
    assert payload["mcpServers"]["willow-mcp"]["env"]["WILLOW_STORE_ROOT"] == str(
        (wh / "store").resolve()
    )


def test_merge_product_projects_from_seed(tmp_path, monkeypatch):
    wh = tmp_path / ".willow"
    monkeypatch.setenv("WILLOW_HOME", str(wh))
    reg_path = wh / "mcp" / "projects.json"
    reg_path.parent.mkdir(parents=True)
    reg_path.write_text(
        json.dumps(
            {
                "version": 1,
                "projects": {
                    "willow": {
                        "path": "{{HOME}}/github/willow",
                        "agent": "willow",
                        "servers": ["willow-mcp"],
                        "env": {"WILLOW_STORE_ROOT": "{{HOME}}/github/willow/.willow/store"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    data = load_registry(bootstrap=False)
    assert "WILLOW_STORE_ROOT" not in (data["projects"]["willow"].get("env") or {})


def test_ensure_registry_from_seed(tmp_path, monkeypatch):
    wh = tmp_path / ".willow"
    monkeypatch.setenv("WILLOW_HOME", str(wh))

    path = ensure_registry(dry_run=False)
    assert path.is_file()
    data = load_registry(bootstrap=False)
    assert "willow" in data["projects"]
    assert "github" in data["projects"]


def test_audit_all_skips_symlink_alias_roots(tmp_path, monkeypatch):
    wh = tmp_path / ".willow"
    monkeypatch.setenv("WILLOW_HOME", str(wh))

    canonical = tmp_path / "store-public"
    canonical.mkdir()
    alias = tmp_path / "store-alias"
    alias.symlink_to(canonical, target_is_directory=True)
    (canonical / ".cursor").mkdir(parents=True, exist_ok=True)

    registry = {
        "version": 1,
        "projects": {
            "store-public": {
                "path": str(canonical),
                "agent": "willow",
                "servers": ["willow-mcp"],
                "ides": ["cursor", "claude"],
                "wiring": {"hooks": True, "active_agent": False, "claude_settings": "project"},
            },
            "store-alias": {
                "path": str(alias),
                "agent": "willow",
                "servers": ["willow-mcp"],
                "ides": ["cursor", "claude"],
                "wiring": {"hooks": True, "active_agent": False, "claude_settings": "project"},
            },
        },
    }
    reg_path = wh / "mcp" / "projects.json"
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(json.dumps(registry), encoding="utf-8")

    for pid in ("store-public", "store-alias"):
        sync_project(pid, registry["projects"][pid], dry_run=False)

    issues = audit_all()
    assert issues == []
