"""Tests for mcp_federation: discovery, spec parsing, and the ratified
registry — steps 1-2 of docs/design/federated-mcp-gating.md §9."""
import json

import pytest

from willow_mcp import mcp_federation as mf


# ── _stable_id / McpServerSpec ────────────────────────────────────────────────

def test_stable_id_is_deterministic_and_namespace_sensitive():
    a = mf._stable_id("/usr/bin/foo", "server-a")
    b = mf._stable_id("/usr/bin/foo", "server-a")
    c = mf._stable_id("/usr/bin/foo", "server-b")
    d = mf._stable_id("/usr/bin/bar", "server-a")
    assert a == b
    assert a != c  # same binary, different name -> different identity
    assert a != d  # different binary, same name -> different identity
    assert len(a) == 12


def test_spec_round_trips_through_dict():
    spec = mf.McpServerSpec(
        id="abc123", name="fs", command="node", args=("server.js",),
        env_keys=("API_KEY",), cwd="/tmp", transport="stdio",
        source_path="/repo/.mcp.json",
    )
    back = mf.McpServerSpec.from_dict(spec.to_dict())
    assert back == spec


# ── parse_mcp_json ─────────────────────────────────────────────────────────

def test_parse_mcp_json_handles_mcpServers_key(tmp_path):
    p = tmp_path / ".mcp.json"
    p.write_text(json.dumps({
        "mcpServers": {"fs": {"command": "node", "args": ["server.js"], "env": {"X": "1"}}}
    }))
    specs = mf.parse_mcp_json(p)
    assert len(specs) == 1
    assert specs[0].name == "fs"
    assert specs[0].command == "node"
    assert specs[0].env_keys == ("X",)
    assert specs[0].source_path == str(p)


def test_parse_mcp_json_handles_servers_key_and_type_field(tmp_path):
    p = tmp_path / ".mcp.json"
    p.write_text(json.dumps({
        "servers": {"gazelle": {"type": "stdio", "command": "python3", "args": ["-m", "x"]}}
    }))
    specs = mf.parse_mcp_json(p)
    assert len(specs) == 1
    assert specs[0].name == "gazelle"
    assert specs[0].transport == "stdio"


def test_parse_mcp_json_skips_entry_missing_command_but_keeps_the_rest(tmp_path):
    p = tmp_path / ".mcp.json"
    p.write_text(json.dumps({"mcpServers": {
        "broken": {"args": ["nothing"]},
        "ok": {"command": "true"},
    }}))
    specs = mf.parse_mcp_json(p)
    assert [s.name for s in specs] == ["ok"]


def test_parse_mcp_json_never_raises_on_malformed_file(tmp_path):
    p = tmp_path / ".mcp.json"
    p.write_text("{not json")
    assert mf.parse_mcp_json(p) == []


def test_parse_mcp_json_never_stores_env_values_only_key_names(tmp_path):
    p = tmp_path / ".mcp.json"
    p.write_text(json.dumps({"mcpServers": {
        "svc": {"command": "true", "env": {"SECRET_TOKEN": "sk-super-secret-value"}}
    }}))
    specs = mf.parse_mcp_json(p)
    dumped = json.dumps(specs[0].to_dict())
    assert "sk-super-secret-value" not in dumped
    assert "SECRET_TOKEN" in dumped


# ── discovery / shadow-IT ──────────────────────────────────────────────────

def test_discover_mcp_json_files_skips_reserved_dirs(tmp_path):
    (tmp_path / "proj" / "node_modules" / "dep").mkdir(parents=True)
    (tmp_path / "proj" / "node_modules" / "dep" / ".mcp.json").write_text("{}")
    (tmp_path / "proj").mkdir(exist_ok=True)
    (tmp_path / "proj" / ".mcp.json").write_text("{}")
    found = mf.discover_mcp_json_files(tmp_path)
    assert (tmp_path / "proj" / ".mcp.json") in found
    assert not any("node_modules" in p.parts for p in found)


def test_discover_mcp_json_files_on_missing_root_returns_empty(tmp_path):
    assert mf.discover_mcp_json_files(tmp_path / "does-not-exist") == []


def test_unregistered_mcp_files_is_discovery_minus_ratified_sources(tmp_path, home):
    (tmp_path / "proj").mkdir()
    p = tmp_path / "proj" / ".mcp.json"
    p.write_text(json.dumps({"mcpServers": {"svc": {"command": "true"}}}))

    # Nothing ratified yet: the file is unregistered (shadow IT).
    assert p in mf.unregistered_mcp_files(tmp_path)

    spec = mf.parse_mcp_json(p)[0]
    mf.ratify(spec, ratified_by="operator", reason="test")

    # Ratifying the entry drawn from this file removes it from the shadow list.
    assert p not in mf.unregistered_mcp_files(tmp_path)


# ── ratified registry ───────────────────────────────────────────────────────

def _spec(name="svc", command="true", env_keys=()):
    resolved = mf._resolved_command_path(command)
    return mf.McpServerSpec(
        id=mf._stable_id(resolved, name), name=name, command=command,
        env_keys=env_keys, source_path="/repo/.mcp.json",
    )


def test_ratify_then_list_and_get(home):
    spec = _spec()
    entry = mf.ratify(spec, ratified_by="operator", reason="onboarding")
    assert entry["ratified_by"] == "operator"
    assert mf.is_ratified(spec.id)
    got = mf.get_ratified(spec.id)
    assert got["id"] == spec.id
    listed = mf.list_ratified()
    assert any(e["id"] == spec.id for e in listed)


def test_ratify_requires_attribution(home):
    with pytest.raises(ValueError):
        mf.ratify(_spec(), ratified_by="")


def test_unratified_server_id_is_not_ratified(home):
    assert mf.is_ratified("nonexistent") is False
    assert mf.get_ratified("nonexistent") is None
    assert mf.list_ratified() == []


def test_revoke_ratification_removes_the_entry(home):
    spec = _spec()
    mf.ratify(spec, ratified_by="operator")
    assert mf.is_ratified(spec.id)
    assert mf.revoke_ratification(spec.id) is True
    assert mf.is_ratified(spec.id) is False
    # Revoking again is a no-op, reported honestly.
    assert mf.revoke_ratification(spec.id) is False


def test_re_ratifying_the_same_id_overwrites_rather_than_duplicates(home):
    spec = _spec()
    mf.ratify(spec, ratified_by="alice", reason="first")
    mf.ratify(spec, ratified_by="bob", reason="corrected env_keys")
    listed = mf.list_ratified()
    assert len(listed) == 1
    assert listed[0]["ratified_by"] == "bob"


def test_corrupt_registry_file_denies_all_rather_than_partially_trusting(home):
    mf.federation_dir().mkdir(parents=True, exist_ok=True)
    mf.registry_path().write_text("{not valid json")
    assert mf.list_ratified() == []
    assert mf.is_ratified("anything") is False


# ── load_server_env: allowlist, never inheritance (Decision 4a) ─────────────

def test_load_server_env_only_passes_named_keys(monkeypatch):
    monkeypatch.setenv("WILLOW_FED_TEST_KEY", "value-a")
    monkeypatch.setenv("WILLOW_FED_TEST_UNLISTED", "should-not-leak")
    env = mf.load_server_env({"env_keys": ["WILLOW_FED_TEST_KEY", "WILLOW_FED_TEST_ABSENT"]})
    assert env == {"WILLOW_FED_TEST_KEY": "value-a"}
    assert "WILLOW_FED_TEST_UNLISTED" not in env


def test_load_server_env_empty_env_keys_yields_empty_environment(monkeypatch):
    monkeypatch.setenv("WILLOW_PGP_FINGERPRINT", "deadbeef")
    assert mf.load_server_env({"env_keys": []}) == {}
    assert mf.load_server_env({}) == {}
