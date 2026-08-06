import json

from willow_mcp import stack_snapshot as ss
from willow_mcp.db import Store


def _manifest(tmp_path, monkeypatch, app="willow", scope=None):
    root = tmp_path / "mcp_apps"
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(root))
    path = root / app / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "permissions": ["orchestrator", "full_access"],
                "store_scope": scope or ["projects_willow_*", "willow_*"],
                "collection_aliases": {"stack": "projects_willow_stack"},
            }
        )
    )


def test_write_and_read_stack_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("WILLOW_PG_DB", "nonexistent_db_for_test")
    out = ss.write_stack_snapshot("hanuman", "sess-1", project="willow-mcp")
    assert out.get("ok") is True
    snap = ss.read_stack_snapshot("hanuman")
    assert snap.get("session_id") == "sess-1"
    assert snap.get("agent") == "hanuman"
    assert "written_at" in snap


def test_session_enter_orientation_includes_snapshot(tmp_path, monkeypatch):
    from willow_mcp import server

    _manifest(tmp_path, monkeypatch)
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    store = Store(tmp_path / "store")
    store.put(
        ss.stack_collection("willow"),
        {
            "session_id": "prior",
            "open_tasks": [{"id": "t1", "title": "finish gate", "status": "pending"}],
            "written_at": "2026-08-06T00:00:00Z",
        },
        record_id="current",
    )
    monkeypatch.setattr(server, "_store", store)
    assert ss.read_stack_snapshot("willow").get("session_id") == "prior"
    project = tmp_path / "repo"
    project.mkdir()
    entered = server.session_enter(
        app_id="willow",
        session_id="fresh",
        project="repo",
        workspace=str(project),
    )
    snap = entered["orientation"]["stack_snapshot"]
    assert snap.get("session_id") == "prior"
    assert snap["open_tasks"][0]["title"] == "finish gate"


def test_session_stop_hook_writes_snapshot(tmp_path, monkeypatch):
    import io

    from willow_mcp import session_stop_hook as stop

    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("WILLOW_APP_ID", "hanuman")
    monkeypatch.setattr(stop.sys, "stdin", io.StringIO(json.dumps({"session_id": "end-1"})))
    stop.main()
    snap = ss.read_stack_snapshot("hanuman")
    assert snap.get("session_id") == "end-1"
