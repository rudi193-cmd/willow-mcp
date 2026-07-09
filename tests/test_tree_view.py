"""Tests for tree_view.py — the build_tree() integration seam a real
dashboard calls instead of assembling fleet_status/fleet_health/etc. itself.

No live Postgres in this test environment, so sap/canopy/leaves exercise the
fail-soft `{"error": "postgres_unavailable"}` path throughout — that IS the
behavior under test for those three; roots/rings/litter/stomata are local
SQLite/filesystem and are asserted on for real content.
"""
import json

import pytest

from willow_mcp import manifest_admin, server, tree_view


@pytest.fixture(autouse=True)
def _fresh_rate_buckets():
    """_buckets is a module-global in server.py — every build_tree() call
    makes several _guarded calls under the same app_id, so without a reset
    per test, repeated calls to the same app_id (e.g. "testapp", used all
    over this suite) trip the rate limiter and a later test sees
    'rate_limited' instead of the condition it's actually testing."""
    server._buckets.clear()
    yield
    server._buckets.clear()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "mcp_apps"))
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("WILLOW_MCP_RECEIPT_DB", str(tmp_path / "receipts.db"))
    monkeypatch.delenv("WILLOW_HUMAN_ORCHESTRATOR", raising=False)
    # Hermetic: this suite exercises the `postgres_unavailable` degradation path
    # (see module docstring). Force it regardless of whether a Postgres happens
    # to be reachable on the machine running the tests — otherwise a live local
    # Postgres flips sap/canopy/leaves to real data and auto-writes a schema-map
    # artifact (inflating rings["total"]), making results depend on the dev's
    # environment rather than the code.
    monkeypatch.setattr(server, "get_pg", lambda: None)
    return tmp_path


def _write_schema_map(tmp_path, app_id, table, confirmed, schema_drift=False):
    root = tmp_path / "mcp_apps" / app_id / "schema_maps"
    root.mkdir(parents=True, exist_ok=True)
    record = {"table": table, "confirmed": confirmed, "schema_drift": schema_drift,
              "discovered_at": "2026-01-01T00:00:00+00:00"}
    (root / f"deadbeef__{table}.json").write_text(json.dumps(record))


# ── _roots ───────────────────────────────────────────────────────────────────

def test_roots_lists_collections(home):
    manifest_admin.set_permission("testapp", "store_read", True)
    from willow_mcp.db import Store
    Store().put("mycollection", {"hello": "world"})
    roots = tree_view._roots("testapp")
    assert "mycollection" in roots["collections"]
    assert roots["count"] == 1
    assert roots["scoped"] is False  # no store_scope set on the manifest


def test_roots_empty_when_no_collections(home):
    """No manifest for "nobody" -> gate.store_scope denies-all ([], not None)
    -> _roots correctly reports scoped=True with zero collections, matching
    gate.py's fail-closed default rather than treating no-manifest as
    unscoped access."""
    roots = tree_view._roots("nobody")
    assert roots == {"collections": [], "count": 0, "scoped": True}


def test_roots_honors_store_scope(home):
    manifest = manifest_admin.read_manifest("scopedapp")
    manifest["store_scope"] = ["scopedapp_*"]
    manifest["permissions"] = ["store_read"]
    manifest_admin._write_json_atomic(manifest_admin.manifest_path("scopedapp"), manifest)

    from willow_mcp.db import Store
    store = Store()
    store.put("scopedapp_notes", {"a": 1})
    store.put("someone_elses_stuff", {"b": 2})

    roots = tree_view._roots("scopedapp")
    assert roots["collections"] == ["scopedapp_notes"]
    assert roots["scoped"] is True


# ── _rings ───────────────────────────────────────────────────────────────────

def test_rings_empty_when_no_schema_maps(home):
    assert tree_view._rings("testapp") == {"tables": [], "confirmed": 0, "total": 0}


def test_rings_reflects_confirmed_and_unconfirmed(home):
    _write_schema_map(home, "testapp", "tasks", confirmed=True)
    _write_schema_map(home, "testapp", "agents", confirmed=False)
    rings = tree_view._rings("testapp")
    assert rings["total"] == 2
    assert rings["confirmed"] == 1
    names = {t["table"] for t in rings["tables"]}
    assert names == {"tasks", "agents"}


def test_rings_surfaces_schema_drift(home):
    _write_schema_map(home, "testapp", "tasks", confirmed=False, schema_drift=True)
    rings = tree_view._rings("testapp")
    assert rings["tables"][0]["schema_drift"] is True


def test_rings_ignores_malformed_files(home):
    root = home / "mcp_apps" / "testapp" / "schema_maps"
    root.mkdir(parents=True)
    (root / "garbage.json").write_text("{not json")
    assert tree_view._rings("testapp") == {"tables": [], "confirmed": 0, "total": 0}


# ── _girth ───────────────────────────────────────────────────────────────────

def test_girth_sums_every_countable_part():
    rings = {"total": 3, "confirmed": 2}
    roots = {"count": 4}
    leaves = {"atoms": [{"id": "1"}, {"id": "2"}]}
    litter = {"receipts": [{"tool": "store_put"}]}
    g = tree_view._girth(rings, roots, leaves, litter)
    assert g == {"total": 10, "rings": 3, "roots": 4, "leaves": 2, "litter": 1}


def test_girth_treats_postgres_errored_parts_as_zero():
    """A tree with no database still has a girth — the unreachable
    Postgres-backed parts contribute 0, they don't blow up the sum."""
    g = tree_view._girth(
        rings={"total": 2, "confirmed": 1},
        roots={"count": 1},
        leaves={"error": "postgres_unavailable"},
        litter={"error": "postgres_unavailable"},
    )
    assert g == {"total": 3, "rings": 2, "roots": 1, "leaves": 0, "litter": 0}


def test_girth_of_a_bare_seed_is_zero():
    g = tree_view._girth({"total": 0}, {"count": 0}, {"error": "x"}, {"error": "x"})
    assert g["total"] == 0


def test_girth_erupts_only_once_it_has_thickness(caplog):
    """The known-issue log line fires when — and only when — the trunk has
    actually put on girth. A bare seed calculates girth silently; a tree with
    any accumulated growth announces it. (Priority: Won't Fix.)

    The assertion is deliberately spelled letter-by-letter so the literal log
    string lives in exactly ONE place in this whole repository — the
    logger.info call in tree_view.py. Grep it and you get a single hit. The
    story it comes from depends on that being true.
    """
    erupted = "Girth" + " " + "erupted."

    with caplog.at_level("INFO", logger="willow_mcp.tree_view"):
        tree_view._girth({"total": 0}, {"count": 0}, {"error": "x"}, {"error": "x"})
    seed_messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("Calculating girth") for m in seed_messages)
    assert erupted not in seed_messages  # a seed does not erupt

    caplog.clear()
    with caplog.at_level("INFO", logger="willow_mcp.tree_view"):
        tree_view._girth({"total": 1}, {"count": 0}, {"error": "x"}, {"error": "x"})
    grown_messages = [r.getMessage() for r in caplog.records]
    assert erupted in grown_messages


# ── build_tree ───────────────────────────────────────────────────────────────

def test_build_tree_has_every_part(home):
    manifest_admin.set_permission("testapp", "full_access", True)
    tree = tree_view.build_tree("testapp")
    assert set(tree.keys()) == {
        "app_id", "trunk", "sap", "canopy", "roots", "rings", "leaves",
        "litter", "stomata",
    }
    assert tree["app_id"] == "testapp"


def test_build_tree_degrades_without_postgres(home):
    manifest_admin.set_permission("testapp", "full_access", True)
    tree = tree_view.build_tree("testapp")
    assert tree["sap"] == {"error": "postgres_unavailable"}
    assert tree["canopy"] == {"error": "postgres_unavailable"}
    assert tree["leaves"] == {"error": "postgres_unavailable"}
    # trunk's task/agent rollups must not fabricate numbers when their source erred
    assert tree["trunk"]["tasks_total"] is None
    assert tree["trunk"]["agents"] is None


def test_build_tree_trunk_reflects_real_rings_count(home):
    manifest_admin.set_permission("testapp", "full_access", True)
    _write_schema_map(home, "testapp", "tasks", confirmed=True)
    _write_schema_map(home, "testapp", "agents", confirmed=False)
    tree = tree_view.build_tree("testapp")
    assert tree["trunk"]["tables_ringed"] == 1
    assert tree["trunk"]["tables_total"] == 2


def test_build_tree_trunk_carries_girth(home):
    """Girth rides in the trunk (not a new top-level part) and reflects the
    real accumulated growth — here, two rings, so the tree has thickness."""
    manifest_admin.set_permission("testapp", "full_access", True)
    _write_schema_map(home, "testapp", "tasks", confirmed=True)
    _write_schema_map(home, "testapp", "agents", confirmed=False)
    tree = tree_view.build_tree("testapp")
    girth = tree["trunk"]["girth"]
    assert girth["rings"] == 2
    assert girth["total"] >= 2  # rings, plus whatever roots/litter exist


def test_build_tree_stomata_matches_gates_panel(home):
    manifest_admin.set_permission("testapp", "store_read", True)
    from willow_mcp import gates_panel
    tree = tree_view.build_tree("testapp")
    expected_ids = {row.id for row in gates_panel.collect("testapp")}
    actual_ids = {row["id"] for row in tree["stomata"]}
    assert actual_ids == expected_ids


def test_build_tree_denies_gracefully_without_permissions(home):
    """An app with no manifest at all should still get a full tree shape back
    — the guarded parts (sap/canopy/leaves/litter) come back gate-denied,
    not a crash."""
    tree = tree_view.build_tree("ghost_app")
    assert tree["sap"].get("error") is not None
    assert tree["litter"].get("error") is not None or tree["litter"] == {"receipts": []}


# ── render_summary ───────────────────────────────────────────────────────────

def test_render_summary_handles_all_error_parts(home):
    manifest_admin.set_permission("testapp", "full_access", True)
    tree = tree_view.build_tree("testapp")
    out = tree_view.render_summary(tree)
    assert "postgres_unavailable" in out
    assert "willow-mcp tree" in out
    assert "stomata" in out


def test_render_summary_handles_non_error_sap_and_canopy():
    tree = {
        "app_id": "demo",
        "trunk": {"verdict": "ok", "tasks_total": 5, "tasks_failed": 1,
                  "tasks_pending": 2, "agents": 3, "tables_ringed": 2, "tables_total": 2},
        "sap": {"pending": 2, "running": 0, "completed": 3, "failed": 1, "total": 5,
                "workers": {"alive": 1}, "stranded": False},
        "canopy": {"agents": [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]},
        "roots": {"collections": ["x"], "count": 1, "scoped": False},
        "rings": {"tables": [], "confirmed": 2, "total": 2},
        "leaves": {"atoms": [{"id": "1"}]},
        "litter": {"receipts": [{"tool": "store_put"}]},
        "stomata": [{"state": "on"}, {"state": "off"}],
    }
    out = tree_view.render_summary(tree)
    assert "3 agents" in out
    assert "1 atoms" in out
    assert "1/2 open" in out
