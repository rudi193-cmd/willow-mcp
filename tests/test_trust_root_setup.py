"""Tests for B-32 trust-root hardening operator tooling."""

from __future__ import annotations

import json

import pytest

from willow_mcp import home_init as hi
from willow_mcp import paths
from willow_mcp import trust_root_setup as trs


def test_audit_reports_forgeable_paths_on_default_home(home, monkeypatch):
    # "default home" has to mean a default ENVIRONMENT too. This asserts
    # strict_trust_root is off, and WILLOW_MCP_STRICT_TRUST_ROOT is inherited —
    # so on an install that runs strict mode (this repo's own MCP config does)
    # the test failed while reporting nothing about the code. The sibling test
    # below sets the variable on purpose; this one must clear it on purpose.
    monkeypatch.delenv("WILLOW_MCP_STRICT_TRUST_ROOT", raising=False)
    hi.ensure_home_layout()
    audit = trs.audit_trust_root("hanuman")
    assert audit["strict_trust_root"] is False
    assert audit["hardened"] is False
    keys = {item["key"] for item in audit["forgeable"]}
    assert "lease_root" in keys


def test_audit_hardened_when_strict_and_nothing_forgeable(home, monkeypatch):
    hi.ensure_home_layout()
    monkeypatch.setenv("WILLOW_MCP_STRICT_TRUST_ROOT", "1")
    monkeypatch.setattr(trs.lease, "self_writable_trust_paths", lambda *_: [])
    monkeypatch.setattr(trs.lease, "path_is_self_writable_or_replaceable", lambda *_: False)
    monkeypatch.setattr(trs.lease, "path_is_directly_writable_for_trust", lambda *_: False)
    audit = trs.audit_trust_root("hanuman")
    assert audit["hardened"] is True


def test_merge_strict_env_into_mcp_json(tmp_path):
    mcp_json = tmp_path / ".cursor" / "mcp.json"
    mcp_json.parent.mkdir(parents=True)
    mcp_json.write_text(
        json.dumps({"mcpServers": {"willow-mcp": {"command": "willow-mcp"}}}) + "\n",
        encoding="utf-8",
    )
    assert trs.merge_mcp_env(mcp_json, trs.mcp_env_snippet()) is True
    data = json.loads(mcp_json.read_text(encoding="utf-8"))
    assert data["mcpServers"]["willow-mcp"]["env"]["WILLOW_MCP_STRICT_TRUST_ROOT"] == "1"


def test_harden_dry_run_lists_actions(home, monkeypatch):
    hi.ensure_home_layout()
    monkeypatch.setattr(trs, "resolve_trust_owner", lambda owner: "operator")
    result = trs.harden_trust_root(owner="operator", dry_run=True)
    assert result["filesystem"]["dry_run"] is True
    assert any("chown -R operator:operator" in action for action in result["filesystem"]["actions"])
    assert any("find " in action and "chmod 644" in action for action in result["filesystem"]["actions"])


def test_chmod_tree_uses_privileged_find(home, monkeypatch):
    hi.ensure_home_layout()
    calls: list[list[str]] = []

    def _capture(argv, *, dry_run):
        calls.append(list(argv))

    monkeypatch.setattr(trs, "_run_privileged", _capture)
    trs._chmod_tree(paths.mcp_apps_root(), dir_mode=0o755, file_mode=0o644)
    assert any(cmd[:4] == ["find", str(paths.mcp_apps_root()), "-type", "f"] for cmd in calls)
    assert any(cmd[:4] == ["find", str(paths.mcp_apps_root()), "-type", "d"] for cmd in calls)


def test_resolve_trust_owner_requires_existing_user(monkeypatch):
    def _missing(_name):
        raise KeyError("missing")

    monkeypatch.setattr(trs.pwd, "getpwnam", _missing)
    with pytest.raises(ValueError, match="does not exist"):
        trs.resolve_trust_owner("nobody-here")


def test_resolve_trust_owner_accepts_existing_user(monkeypatch):
    monkeypatch.setattr(trs.pwd, "getpwnam", lambda name: object())
    assert trs.resolve_trust_owner("operator") == "operator"


def test_trust_root_directories_include_mcp_apps_and_config(home):
    hi.ensure_home_layout()
    roots = {p.name for p in trs.trust_root_directories()}
    assert "mcp_apps" in roots
    assert "config" in roots
    assert paths.willow_home().name not in {p.name for p in trs.trust_root_directories() if p == paths.willow_home()}


def test_trust_root_directories_skip_home_root_when_legacy_policy_files_exist(home):
    hi.ensure_home_layout()
    legacy = paths.consent_legacy_path()
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"consent": {"internet": false, "cloud_llm": false, "lan": false}}\n', encoding="utf-8")
    roots = trs.trust_root_directories()
    assert paths.willow_home() not in roots
    assert legacy in trs.trust_policy_files()


def test_runtime_writable_includes_store_not_config(home):
    hi.ensure_home_layout()
    names = {p.name for p in trs.runtime_writable_directories()}
    assert "store" in names
    assert "config" not in names
    assert "mcp_apps" not in names


def test_repair_runtime_dry_run_targets_store(home, monkeypatch):
    hi.ensure_home_layout()
    monkeypatch.setattr(trs, "resolve_runtime_user", lambda _user: "runtime")
    result = trs.repair_runtime_permissions(dry_run=True)
    assert result["runtime_user"] == "runtime"
    assert any("store" in target for target in result["targets"])
    assert any("chown -R runtime:runtime" in action for action in result["actions"])


# ── secret-file exposure (#181 audit finding) ────────────────────────────────
#
# Found live: repair-runtime-perms' generic runtime-children sweep gave
# vault.key/vault.db/mcp_token.json the SAME world-readable 0644/0755 it
# gives ordinary runtime state -- verified by creating a real vault, running
# repair_runtime_permissions() for real (not dry_run), and watching vault.key
# go from its own 0600 default to 0644. The server (running as the runtime
# user) still needs to read these, so they can't move to the trust owner
# like the egress key did -- same owner, stricter mode: owner-only, always.

def test_repair_runtime_dry_run_plans_owner_only_mode_for_vault_key(home, monkeypatch):
    (home / "vault.key").write_text("fernet-key-placeholder")
    monkeypatch.setattr(trs, "resolve_runtime_user", lambda _user: "runtime")
    result = trs.repair_runtime_permissions(dry_run=True)
    vault_key = str(home / "vault.key")
    assert any(f"chmod 600 {vault_key}" in a for a in result["actions"])
    assert not any(f"chmod 644 {vault_key}" in a for a in result["actions"])


def test_repair_runtime_dry_run_plans_owner_only_mode_for_mcp_token(home, monkeypatch):
    (home / "mcp_token.json").write_text("{}")
    monkeypatch.setattr(trs, "resolve_runtime_user", lambda _user: "runtime")
    result = trs.repair_runtime_permissions(dry_run=True)
    token_path = str(home / "mcp_token.json")
    assert any(f"chmod 600 {token_path}" in a for a in result["actions"])
    assert not any(f"chmod 644 {token_path}" in a for a in result["actions"])


def test_repair_runtime_dry_run_leaves_ordinary_files_world_readable(home, monkeypatch):
    """The fix is scoped to the named secret files -- everything else keeps
    the world-readable mode the gate/runtime state actually needs."""
    hi.ensure_home_layout()
    monkeypatch.setattr(trs, "resolve_runtime_user", lambda _user: "runtime")
    result = trs.repair_runtime_permissions(dry_run=True)
    assert any("chmod 644" in a for a in result["actions"])
    assert any("chmod 755" in a for a in result["actions"])


def test_secret_file_exposure_empty_when_nothing_present(home):
    assert trs.secret_file_exposure() == []


def test_secret_file_exposure_detects_world_readable_vault_key(home):
    key = home / "vault.key"
    key.write_text("fernet-key-placeholder")
    key.chmod(0o644)
    exposure = trs.secret_file_exposure()
    assert {"vault.key"} == {e["key"] for e in exposure}
    assert exposure[0]["mode"] == oct(0o644)


def test_secret_file_exposure_silent_when_properly_protected(home):
    key = home / "vault.key"
    key.write_text("fernet-key-placeholder")
    key.chmod(0o600)
    assert trs.secret_file_exposure() == []


def test_audit_trust_root_not_hardened_when_secret_file_exposed(home, monkeypatch):
    monkeypatch.setattr(trs.lease, "self_writable_trust_paths", lambda *_: [])
    monkeypatch.setattr(trs.lease, "path_is_self_writable_or_replaceable", lambda *_: False)
    monkeypatch.setattr(trs.lease, "path_is_directly_writable_for_trust", lambda *_: False)
    monkeypatch.setenv("WILLOW_MCP_STRICT_TRUST_ROOT", "1")
    (home / "mcp_token.json").write_text("{}")
    (home / "mcp_token.json").chmod(0o644)
    audit = trs.audit_trust_root("hanuman")
    assert audit["hardened"] is False
    assert audit["secret_file_exposure"]


# ── egress key hardening (#182) ──────────────────────────────────────────────
#
# egress_trust_directory() resolves via egress_setup.config_dir(), which
# defaults to ~/.config/willow-mcp/egress — NOT under $WILLOW_HOME, so `home`
# alone does not isolate it. Every test here pins WILLOW_MCP_EGRESS_CONFIG_DIR
# into tmp_path first, or it would chown/chmod the real host directory.

@pytest.fixture
def egress_dir(tmp_path, monkeypatch):
    d = tmp_path / "egress-config"
    monkeypatch.setenv("WILLOW_MCP_EGRESS_CONFIG_DIR", str(d))
    return d


def test_egress_trust_directory_resolves_the_isolated_config_dir(egress_dir):
    assert trs.egress_trust_directory() == egress_dir


def test_egress_trust_directory_is_not_one_of_trust_root_directories(home, egress_dir):
    """The whole point of #182: this directory lives outside $WILLOW_HOME by
    design, so the pre-existing hardening loop never touched it."""
    hi.ensure_home_layout()
    assert egress_dir not in trs.trust_root_directories()


def test_apply_egress_key_hardening_reports_absent_when_never_set_up(egress_dir, monkeypatch):
    monkeypatch.setattr(trs, "resolve_trust_owner", lambda owner: "operator")
    result = trs.apply_egress_key_hardening("operator", dry_run=False)
    assert result["present"] is False
    assert result["actions"] == []


def test_apply_egress_key_hardening_uses_owner_only_mode_not_world_readable(egress_dir, monkeypatch):
    """The critical distinction from apply_trust_root_hardening: 0700/0600, not
    the 0755/0644 policy files use — a readable key needs no forgery at all."""
    egress_dir.mkdir()
    (egress_dir / "private.pem").write_text("-----BEGIN PRIVATE KEY-----\n")
    monkeypatch.setattr(trs, "resolve_trust_owner", lambda owner: "operator")
    result = trs.apply_egress_key_hardening("operator", dry_run=True)
    assert result["present"] is True
    assert any("chown -R operator:operator" in a and str(egress_dir) in a for a in result["actions"])
    assert any("chmod 600" in a for a in result["actions"])
    assert any("chmod 700" in a for a in result["actions"])
    assert not any("chmod 644" in a for a in result["actions"])
    assert not any("chmod 755" in a for a in result["actions"])


def test_harden_trust_root_includes_the_egress_step(home, egress_dir, monkeypatch):
    """ensure_home_layout() already provisions a real keypair into egress_dir
    (home_init.py calls egress_setup.ensure_keypair()) — no need to fake one."""
    hi.ensure_home_layout()
    monkeypatch.setattr(trs, "resolve_trust_owner", lambda owner: "operator")
    result = trs.harden_trust_root(owner="operator", dry_run=True)
    assert "egress" in result["filesystem"]
    assert result["filesystem"]["egress"]["present"] is True
    assert any("chmod 600" in a for a in result["filesystem"]["actions"])


def test_audit_trust_root_reports_the_egress_key_when_self_readable(home, egress_dir, monkeypatch):
    egress_dir.mkdir()
    key = egress_dir / "private.pem"
    key.write_text("-----BEGIN PRIVATE KEY-----\n")
    from willow_mcp import egress_setup
    monkeypatch.setattr(egress_setup, "resolve_private_key_path", lambda: key)
    audit = trs.audit_trust_root("app")
    keys = {f["key"] for f in audit["forgeable"]}
    assert "egress_private_key" in keys


def test_operator_command_hints_mentions_sign_net_task():
    hints = trs.operator_command_hints("operator")
    assert any("sign-net-task" in h for h in hints)


def test_doctor_cli_warns_on_secret_file_exposure(home, monkeypatch, capsys):
    """The doctor CLI's own rendering, not just audit_trust_root()'s dict --
    found live (this PR): the print block only fired when audit['forgeable']
    was truthy, so a secret-file-only exposure computed hardened=False but
    printed nothing, silently hiding it from the operator-facing output."""
    from willow_mcp import server

    (home / "mcp_token.json").write_text("{}")
    (home / "mcp_token.json").chmod(0o644)
    monkeypatch.setattr(server, "diagnostic_summary", lambda app_id: {"checks": {}})

    class _Args:
        app_id = "testapp"
        project_root = ""

    server._cmd_doctor(_Args())
    out = capsys.readouterr().out
    assert "secret_files" in out
    assert "mcp_token.json" in out
    assert "repair-runtime-perms" in out
