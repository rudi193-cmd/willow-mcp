"""Tests for the Nestor tool oracle (willow_mcp.tool_oracle).

Nestor is an optional dependency. The unavailable-path and gate-wiring tests run
everywhere (that is the shape CI without the `nestor` extra sees); the routing
tests self-skip when the engine isn't importable, rather than failing the run.
"""
import json

import pytest

from willow_mcp import gate, tool_oracle


@pytest.fixture()
def oracle_env(tmp_path, monkeypatch):
    # Isolate all oracle state under a temp vault, and default to no shipped
    # catalog so seed does not pull in the real 105-verb bundle.
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("WILLOW_TOOL_ORACLE_BUNDLE", str(tmp_path / "absent.json"))
    return tmp_path


# ── always-on: wiring + degraded path ────────────────────────────────────────
def test_available_returns_bool(oracle_env):
    assert isinstance(tool_oracle.available(), bool)


def test_gate_groups_registered():
    assert "nestor_tool_route" in gate.PERMISSION_GROUPS["tool_oracle_route"]
    assert "nestor_tool_pending" in gate.PERMISSION_GROUPS["tool_oracle_read"]
    # sealing is its own group — a governance write, not folded into route
    assert "nestor_tool_seal" in gate.PERMISSION_GROUPS["tool_oracle_seal"]
    assert "nestor_tool_seal" not in gate.PERMISSION_GROUPS["tool_oracle_route"]


def test_verbs_defined_without_nestor():
    # server must import and expose the verbs even when the engine is absent
    import importlib
    server = importlib.import_module("willow_mcp.server")
    for name in ("nestor_tool_route", "nestor_tool_seal", "nestor_tool_pending"):
        assert callable(getattr(server, name))


def test_unavailable_when_engine_absent(oracle_env):
    if tool_oracle.available():
        pytest.skip("nestor installed — the unavailable path is not exercised here")
    assert tool_oracle.route("anything")["status"] == "unavailable"
    assert tool_oracle.seal("a", "b", "v")["status"] == "unavailable"
    assert tool_oracle.pending()[0]["status"] == "unavailable"


def test_route_rejects_empty_query(oracle_env):
    assert tool_oracle.route("   ")["status"] == "error"


# ── routing (needs the engine) ───────────────────────────────────────────────
def _need_nestor():
    if not tool_oracle.available():
        pytest.skip("needs the optional nestor engine")


def test_seal_then_route_serves(oracle_env):
    _need_nestor()
    sealed = tool_oracle.seal("check fleet health", "fleet_health", "human:test")
    assert sealed["status"] == "sealed"
    out = tool_oracle.route("check fleet health")
    assert out["status"] == "served"
    assert out["tool"] == "fleet_health"


def test_far_query_queues_and_appears_in_pending(oracle_env):
    _need_nestor()
    tool_oracle.seal("check fleet health", "fleet_health", "human:test")
    out = tool_oracle.route("what is the capital of France")
    assert out["status"] == "queued"
    assert out["tool"] is None
    assert any(p.get("surface") == "what is the capital of France"
               for p in tool_oracle.pending())


def test_near_miss_is_refused_not_guessed(oracle_env):
    _need_nestor()
    # a semantic paraphrase (different words) must NOT be served the verb
    tool_oracle.seal("blast radius of a change", "code_graph_impact", "human:test")
    out = tool_oracle.route("what breaks if I edit this file")
    assert out["status"] == "queued"
    assert out["tool"] is None


def test_tampered_bundle_is_refused(oracle_env, tmp_path, monkeypatch):
    _need_nestor()
    from nestor import cascade, portable
    from nestor.entity import EntityResolver
    from nestor.sqlite_store import SqliteStore

    cascade.set_ledger_path(tmp_path / "gen_ledger.jsonl")
    store = SqliteStore(str(tmp_path / "gen.db"))
    EntityResolver(store, domain="tool").seal(
        surface="verify the chain", canonical="frank_verify", verifier="t")
    bundle = portable.export_bundle(store, source_lang="tool", target_lang="tool")
    # silently redirect a security verb, then re-point the oracle at the tamper
    victim = next(p for p in bundle["pairs"] if p["target_text"] == "frank_verify")
    victim["target_text"] = "frank_disable"
    bad = tmp_path / "tampered.bundle.json"
    bad.write_text(json.dumps(bundle))
    monkeypatch.setenv("WILLOW_TOOL_ORACLE_BUNDLE", str(bad))

    out = tool_oracle.route("verify the chain")
    assert out["status"] == "unavailable"
    assert "verification" in out["detail"]


def test_shipped_bundle_verifies(oracle_env, monkeypatch):
    _need_nestor()
    from pathlib import Path

    from nestor import portable
    monkeypatch.delenv("WILLOW_TOOL_ORACLE_BUNDLE", raising=False)
    shipped = Path(tool_oracle.__file__).parent / "bundle" / "tool_oracle.bundle.json"
    if not shipped.is_file():
        pytest.skip("no shipped catalog in this build")
    ok, _ = portable.verify_bundle(json.loads(shipped.read_text()))
    assert ok
