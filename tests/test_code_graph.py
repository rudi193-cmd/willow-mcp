"""code_graph — the willow-2.0 symbol-graph port, driven through the MCP surface.

The engine (willow_mcp.code_graph) is a verbatim port; these tests drive the six
tools through the whole _guarded pipeline and index a REAL tree (a small fixture
package written to tmp) so the assertions are on actual extracted symbols/edges,
not mocks. The gate split (read vs write) is part of what's under test.
"""
import json
import textwrap

import pytest

from willow_mcp import server
from willow_mcp.receipts import ReceiptLog


def _fn(tool):
    return getattr(tool, "fn", tool)


@pytest.fixture
def mk_app(tmp_path, monkeypatch):
    apps = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps))
    monkeypatch.delenv("WILLOW_CODE_GRAPH_DB", raising=False)
    monkeypatch.setattr(server, "_receipt_log", ReceiptLog(str(tmp_path / "r.db")))
    monkeypatch.setattr(server, "_buckets", {})

    def _mk(app_id, perms):
        d = apps / app_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({"permissions": perms}))
        return app_id

    return _mk


@pytest.fixture
def repo(tmp_path):
    """A tiny source tree with a known class/method/function and an import edge."""
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "base.py").write_text(textwrap.dedent("""
        class Animal:
            def speak(self) -> str:
                return "..."
    """))
    (root / "pkg" / "dog.py").write_text(textwrap.dedent("""
        from pkg.base import Animal

        class Dog(Animal):
            def speak(self) -> str:
                return "woof"

        def make_dog(name: str) -> Dog:
            return Dog()
    """))
    return root


# ── index (write) ─────────────────────────────────────────────────────────────

def test_index_builds_the_graph(mk_app, repo):
    app = mk_app("grapher", ["code_graph_write"])
    out = _fn(server.code_graph_index)(app_id=app, repo_root=str(repo))
    assert out.get("files_indexed", 0) >= 3
    assert out.get("symbols_total", 0) >= 5  # 3 modules + classes + methods + func
    assert out["by_language"].get("python") >= 3


def test_index_missing_repo(mk_app):
    app = mk_app("grapher", ["code_graph_write"])
    out = _fn(server.code_graph_index)(app_id=app, repo_root="/no/such/dir")
    assert "not found" in out.get("error", "")


# ── search / explain / walk / impact (read) over the indexed graph ────────────

@pytest.fixture
def indexed(mk_app, repo):
    app = mk_app("grapher", ["code_graph_write", "code_graph_read"])
    _fn(server.code_graph_index)(app_id=app, repo_root=str(repo))
    return app


def test_search_finds_a_symbol(indexed):
    out = _fn(server.code_graph_search)(app_id=indexed, query="make_dog")
    assert out["count"] >= 1
    assert any(r["name"] == "make_dog" and r["kind"] == "function"
               for r in out["results"])


def test_search_kind_filter(indexed):
    out = _fn(server.code_graph_search)(app_id=indexed, query="Dog", kinds=["class"])
    assert out["results"] and all(r["kind"] == "class" for r in out["results"])


def test_explain_reports_signature_and_edges(indexed):
    out = _fn(server.code_graph_explain)(app_id=indexed, symbol="make_dog")
    assert out["kind"] == "function"
    assert "-> Dog" in out["signature"]
    assert out["file_path"].endswith("dog.py")


def test_explain_inheritance_edge(indexed):
    # Dog inherits Animal → an outbound inherit edge on the class
    out = _fn(server.code_graph_explain)(app_id=indexed, symbol="pkg.dog.Dog")
    vias = {c["via"] for c in out["callees"]}
    assert "inherit" in vias


def test_explain_unknown_symbol(indexed):
    out = _fn(server.code_graph_explain)(app_id=indexed, symbol="nonexistent_zzz")
    assert "not found" in out.get("error", "")


def test_walk_from_anchor(indexed):
    out = _fn(server.code_graph_walk)(app_id=indexed, anchor="pkg.dog")
    assert out["anchor_fqn"] == "pkg.dog"
    assert any("dog.py" in f for f in out["files"])


def test_impact_blast_radius(indexed):
    # pkg/base.py is imported by pkg/dog.py → dog is in base's blast radius
    out = _fn(server.code_graph_impact)(app_id=indexed, file_paths=["pkg/base.py"])
    assert "pkg.base" in out["source_modules"]
    assert any("dog" in f for f in out["affected_files"])


def test_suggest_ranks_files(indexed):
    out = _fn(server.code_graph_suggest)(app_id=indexed, task="make a new dog animal")
    fps = [s["file_path"] for s in out["suggestions"]]
    assert any("dog.py" in f for f in fps)


def test_read_tool_before_index_is_clear(mk_app):
    app = mk_app("grapher", ["code_graph_read"])
    out = _fn(server.code_graph_search)(app_id=app, query="x")
    assert "run code_graph_index first" in out.get("error", "")


# ── gate split ────────────────────────────────────────────────────────────────

def test_read_group_cannot_index(mk_app, repo):
    app = mk_app("reader", ["code_graph_read"])
    out = _fn(server.code_graph_index)(app_id=app, repo_root=str(repo))
    assert "gate denied" in out.get("error", "")


def test_write_group_cannot_search(indexed, mk_app):
    app = mk_app("writer", ["code_graph_write"])
    out = _fn(server.code_graph_search)(app_id=app, query="Dog")
    assert "gate denied" in out.get("error", "")
