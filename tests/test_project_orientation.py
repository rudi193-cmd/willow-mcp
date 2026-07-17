import json

from willow_mcp import dispatch, gate, registry, server
from willow_mcp.db import Store
from willow_mcp.session_start_hook import handle


ALIASES = {
    "stack": "projects_willow_stack",
    "pm/portfolio": "projects_willow_pm_portfolio",
    "pm/milestones": "projects_willow_pm_milestones",
    "pa/commitments": "projects_willow_pa_commitments",
    "governance/flags": "projects_willow_governance_flags",
    "orient": "projects_willow_orient",
}


def _manifest(tmp_path, monkeypatch, app="willow", scope=None):
    root = tmp_path / "mcp_apps"
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(root))
    path = root / app / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "permissions": ["full_access"],
                "store_scope": scope or ["projects_willow_*"],
                "collection_aliases": ALIASES,
            }
        )
    )


def test_manifest_compiler_carries_explicit_aliases():
    reg = registry.load_registry(prefer_home=False)
    row = registry.specialist_row("willow", registry=reg)
    manifest = registry.manifest_from_row(
        row, collection_aliases=reg["collection_aliases"]
    )
    assert manifest["collection_aliases"]["pm/portfolio"] == (
        "projects_willow_pm_portfolio"
    )


def test_aliases_resolve_explicitly_and_canonical_names_remain_available(
    tmp_path, monkeypatch
):
    _manifest(tmp_path, monkeypatch)
    assert gate.resolve_collection_alias("willow", "pm/portfolio") == (
        "projects_willow_pm_portfolio",
        None,
    )
    assert gate.resolve_collection_alias(
        "willow", "projects_willow_pm_portfolio"
    ) == ("projects_willow_pm_portfolio", None)
    assert gate.resolve_collection_alias("willow", "unknown/path")[0] is None


def test_alias_collision_fails_closed(tmp_path, monkeypatch):
    _manifest(tmp_path, monkeypatch)
    path = tmp_path / "mcp_apps" / "willow" / "manifest.json"
    data = json.loads(path.read_text())
    data["collection_aliases"] = {
        "first": "physical",
        "physical": "other",
    }
    path.write_text(json.dumps(data))
    assert gate.collection_aliases("willow") == {}


def test_identity_gate_runs_before_unknown_alias_error(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "missing"))
    result = server.store_list(app_id="unknown", collection="unknown/path")
    assert "gate denied" in result[0]["error"]


def test_alias_scope_is_enforced_on_physical_target(tmp_path, monkeypatch):
    _manifest(tmp_path, monkeypatch, scope=["projects_willow_stack"])
    monkeypatch.setattr(server, "_store", Store(tmp_path / "store"))
    result = server.store_list(
        app_id="willow", collection="pm/portfolio"
    )
    assert "projects_willow_pm_portfolio" in result[0]["error"]


def test_project_orientation_reads_every_declared_collection(
    tmp_path, monkeypatch
):
    _manifest(tmp_path, monkeypatch)
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    store = Store(tmp_path / "store")
    for physical in ALIASES.values():
        store.put(physical, {"kind": physical}, record_id="one")
    monkeypatch.setattr(server, "_store", store)
    project = tmp_path / "charter"
    project.mkdir()
    (project / "ORIENT.md").write_text("# Orient\n")

    entered = server.session_enter(
        app_id="willow",
        session_id="fresh",
        project="charter",
        workspace=str(project),
    )
    assert entered["entry_mode"] == "human_orchestrator"
    assert entered["orientation"]["orient"]["exists"] is True
    assert all(
        entered["orientation"]["records"][logical]
        for logical in (
            "stack",
            "pm/portfolio",
            "pm/milestones",
            "pa/commitments",
            "governance/flags",
        )
    )
    assert entered["orientation"]["frank"]["status"] == "not_present"


def test_project_handoffs_do_not_bleed(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    dispatch.session_handoff_write(
        "hanuman", "s1", narrative="alpha only", project="alpha"
    )
    dispatch.session_handoff_write(
        "hanuman", "s2", narrative="beta only", project="beta"
    )
    alpha = dispatch.latest_project_handoff("hanuman", "alpha")
    beta = dispatch.latest_project_handoff("hanuman", "beta")
    assert "alpha only" in alpha["content"]
    assert "beta only" not in alpha["content"]
    assert "beta only" in beta["content"]


def test_specialist_dispatch_session_receives_project_orientation(
    tmp_path, monkeypatch
):
    _manifest(tmp_path, monkeypatch, app="hanuman")
    monkeypatch.setattr(server, "_store", Store(tmp_path / "store"))
    sent = dispatch.dispatch_send(
        "willow", "hanuman", "# Build\n\nDo the work.", summary="build"
    )
    project = tmp_path / "project"
    project.mkdir()
    entered = server.session_enter(
        app_id="hanuman",
        session_id="dispatch-session",
        dispatch_id=sent["dispatch_id"],
        project="project",
        workspace=str(project),
    )
    assert entered["entry_mode"] == "dispatch"
    assert entered["orientation"]["collection_aliases"] == ALIASES
    assert entered["project"]["name"] == "project"


def test_session_start_bridge_invokes_session_enter_without_legacy_hook(
    monkeypatch
):
    seen = {}

    def enter(**kwargs):
        seen.update(kwargs)
        return {"entry_mode": "human", "persona": "voice context"}

    monkeypatch.setattr(server, "session_enter", enter)
    monkeypatch.setenv("WILLOW_APP_ID", "hanuman")
    result = handle({"session_id": "s", "workspace": "/workspace/project"})
    assert seen["workspace"] == "/workspace/project"
    assert "persona" in json.loads(result["additional_context"])
