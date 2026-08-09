"""AT-M1 — the #181 red-team kill chain, replayed step by step against the
current code, each step asserting refusal.

Not every step is provable in a single-uid pytest process: the OS-level
separation #181 itself calls the actual precondition (a dedicated agent uid
distinct from the one running the MCP server) can't exist inside one test
process that owns every file it touches. Where that's true, the test
documents the residual explicitly rather than pretending to close it.

What IS provable, and proven here:
  Step 1 (self-grant capability)  -> #183: an unsigned self-grant is denied.
  Step 2 (steal the egress key)   -> #182: covered by test_lease.py /
                                     test_trust_root_setup.py's real chmod
                                     assertions; not re-proven here (would
                                     need real chown, which needs real uid
                                     separation to test meaningfully).
  Step 3 (bypass consent)         -> pre-existing: harden-trust-root already
                                     covers config/settings.global.json AND
                                     its legacy copy (trust_policy_files()).
  Step 5 (forge an identity)      -> #183: an unsigned manifest for a NEW
                                     app_id is denied outright, reproducing
                                     the issue's own repro verbatim (whoami
                                     no longer reports a fabricated identity).
  Step 6 (raw DB access)          -> partially guarded (pre_tool_use.py's
                                     check_bash + check_owned_db_file_write),
                                     but those are client-side guardrails,
                                     not OS controls -- see module docstring
                                     in hooks/pre_tool_use.py. #232 closes the
                                     MODE half of the real OS control
                                     (repair-runtime-perms now gives store
                                     .db files owner-only 0700/0600, proven
                                     below by a real chmod, not a dry-run
                                     string assertion). Full closure still
                                     needs the same uid separation as step 1
                                     -- on this single-uid sandbox the
                                     runtime user IS the agent uid, so mode
                                     bits alone cannot refuse a same-uid read
                                     regardless of what they are set to.
"""
import json
import os
import subprocess

import pytest

from willow_mcp import consent, gate, server


def _gen_key(gnupghome, name, email):
    batch = gnupghome / f"{name}.batch"
    batch.write_text(
        "%no-protection\nKey-Type: EDDSA\nKey-Curve: ed25519\n"
        f"Name-Real: {name}\nName-Email: {email}\nExpire-Date: 0\n%commit\n"
    )
    env = {**os.environ, "GNUPGHOME": str(gnupghome)}
    subprocess.run(["gpg", "--batch", "--gen-key", str(batch)],
                    env=env, check=True, capture_output=True, timeout=30)


@pytest.fixture(scope="module")
def gpg_keypair(tmp_path_factory):
    gnupghome = tmp_path_factory.mktemp("gnupghome")
    _gen_key(gnupghome, "Willow Test Operator", "test@willow.invalid")
    env = {**os.environ, "GNUPGHOME": str(gnupghome)}
    out = subprocess.run(["gpg", "--list-secret-keys", "--with-colons"],
                          env=env, check=True, capture_output=True, text=True, timeout=10)
    fpr = next(line.split(":")[9] for line in out.stdout.splitlines() if line.startswith("fpr"))
    return {"gnupghome": str(gnupghome), "fingerprint": fpr}


@pytest.fixture
def pgp_env(gpg_keypair, monkeypatch):
    monkeypatch.setenv("GNUPGHOME", gpg_keypair["gnupghome"])
    monkeypatch.setenv("WILLOW_PGP_FINGERPRINT", gpg_keypair["fingerprint"])


def _write_manifest(home, app_id, **overrides):
    d = home / "mcp_apps" / app_id
    d.mkdir(parents=True, exist_ok=True)
    data = {"app_id": app_id, "permissions": ["store_read"]}
    data.update(overrides)
    path = d / "manifest.json"
    path.write_text(json.dumps(data))
    return path


def test_step1_self_grant_capability_is_denied(home, pgp_env):
    """'add my own manifest full_access and the gate honors it' -- start from
    a signed, legitimate manifest, then self-grant without re-signing."""
    from willow_mcp import pgp

    path = _write_manifest(home, "kart", permissions=["store_read"])
    ok, _ = pgp.sign_detached(path)
    assert ok
    assert gate.permitted("kart", "full_access") is False  # not granted yet, sanity

    # the self-grant: widen permissions in place, without re-signing
    path.write_text(json.dumps({"app_id": "kart", "permissions": ["full_access"]}))
    assert gate.authorized("kart") is False
    assert gate.permitted("kart", "store_get") is False, (
        "a self-granted, unsigned manifest must have no standing at all"
    )


def test_step3_consent_bypass_via_direct_file_write_is_denied(home):
    """'flip consent.internet by writing config/settings.global.json directly'
    -- pre-existing coverage, not new: harden-trust-root already chowns
    config/ (one of trust_root_directories()) to the trust owner, and the
    legacy root copy via trust_policy_files(). consent.settings_path() prefers
    the canonical config/ file but falls back to the legacy root copy when
    the canonical one doesn't exist yet -- both branches must be covered by
    hardening, or an attacker just targets whichever one hardening missed.
    """
    from willow_mcp import trust_root_setup as trs

    # Branch 1: canonical file exists -> config/, a trust_root_directories() root.
    config_settings = home / "config" / "settings.global.json"
    config_settings.parent.mkdir(parents=True, exist_ok=True)
    config_settings.write_text(json.dumps({"internet": True}))
    assert consent.settings_path() == config_settings
    assert config_settings.parent in trs.trust_root_directories()

    # Branch 2: no canonical file -> legacy root copy, covered by trust_policy_files().
    config_settings.unlink()
    legacy_settings = home / "settings.global.json"
    legacy_settings.write_text(json.dumps({"internet": True}))
    assert consent.settings_path() == legacy_settings
    assert legacy_settings in trs.trust_policy_files()


def test_step5_forged_identity_is_denied(home, pgp_env, monkeypatch):
    """The #183 repro verbatim: write mcp_apps/steve/manifest.json with a
    full permission roll and try to become steve via whoami. Unenforced
    binding (WILLOW_MCP_ENFORCE_BINDING unset) matches the red-team run's
    own conditions -- that's not a gap this test introduces, it's the
    environment #181 was filed against."""
    monkeypatch.delenv("WILLOW_MCP_ENFORCE_BINDING", raising=False)
    _write_manifest(
        home, "steve",
        permissions=["store_read", "store_write", "knowledge_write", "full_access"],
        store_scope=["*"],
    )
    result = server.whoami("steve")
    assert result.get("error") == "no_manifest", (
        f"expected the forged identity to have no standing, got: {result}"
    )
    assert "role" not in result
    assert gate.authorized("steve") is False


def test_step5_signing_the_forged_manifest_with_the_real_key_still_requires_the_pin(
    home, gpg_keypair, monkeypatch
):
    """Even a REAL signature doesn't help an attacker without the pinned
    fingerprint -- confirms the pin, not mere possession of 'a' signature,
    is what the gate trusts."""
    monkeypatch.setenv("GNUPGHOME", gpg_keypair["gnupghome"])
    monkeypatch.setenv("WILLOW_PGP_FINGERPRINT", "E" * 40)  # not this key
    from willow_mcp import pgp

    path = _write_manifest(home, "steve", permissions=["full_access"], store_scope=["*"])
    ok, _ = pgp.sign_detached(path)
    assert ok
    assert gate.authorized("steve") is False


def test_step6_raw_bash_client_access_is_guarded_client_side(tmp_path, monkeypatch):
    """The acknowledged residual: pre_tool_use.py's check_bash blocks the
    common raw-client case, but it's a guardrail an unhooked process skips
    entirely -- proven here by exercising the guard directly (it fires) and
    documenting, not hiding, that this is not an OS control (see
    hooks/pre_tool_use.py's own module docstring)."""
    import importlib.util
    from pathlib import Path

    hook_path = Path(__file__).resolve().parent.parent / "hooks" / "pre_tool_use.py"
    spec = importlib.util.spec_from_file_location("pre_tool_use", hook_path)
    pre_tool_use = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pre_tool_use)

    reason = pre_tool_use.check_bash(
        "sqlite3 $WILLOW_STORE_ROOT/col/store.db 'select * from records'"
    )
    assert reason is not None, "the client-side guardrail must still fire"
    # And the file-write path (#181's audit companion, item B from the
    # earlier hooks handoff): a Write/Edit targeting the raw store file.
    reason = pre_tool_use.check_owned_db_file_write({"file_path": "/x/.willow/store/store.db"})
    assert reason is not None


def test_step6b_store_db_files_get_real_os_mode_hardening(home, monkeypatch):
    """The other half of step 6, and the one the hook alone could never
    provide: #232's `repair_runtime_permissions()` now gives store `.db`
    files (store.db per SOIL collection, kart.db, mcp_receipt.db) owner-only
    0700/0600 instead of the world-readable 0755/0644 ordinary runtime state
    gets -- verified here with a REAL chmod (not a dry-run action-string
    assertion), the same method B-46 used for vault.key.

    What this proves: the mode bits genuinely change on disk when hardening
    runs, for the exact db names hooks/pre_tool_use.py's _OWNED_DB_FILE_RE
    names. What it does NOT prove, and cannot on this host: that a different
    uid is refused a read by those bits. This sandbox is single-uid --
    `resolve_runtime_user` is monkeypatched to the CURRENT real account
    below, standing in for the real "runtime user" #231's separation would
    put in that role. See docs/deploy/dedicated-uid-deployment.md's "Store
    .db files (#232)" section for the residual this leaves for a real
    multi-uid host."""
    import os
    import pwd
    import stat

    from willow_mcp import home_init as hi
    from willow_mcp import paths
    from willow_mcp import trust_root_setup as trs

    hi.ensure_home_layout()
    real_user = pwd.getpwuid(os.geteuid()).pw_name

    col_db = paths.store_root() / "knowledge" / "store.db"
    col_db.parent.mkdir(parents=True, exist_ok=True)
    col_db.write_text("sqlite-placeholder")
    col_db.chmod(0o644)
    receipt = home / "mcp_receipt.db"
    receipt.write_text("sqlite-placeholder")
    receipt.chmod(0o644)

    monkeypatch.setattr(trs, "resolve_runtime_user", lambda _u: real_user)
    trs.repair_runtime_permissions(dry_run=False)

    assert stat.S_IMODE(col_db.stat().st_mode) == 0o600, (
        "store.db must be owner-only after repair-runtime-perms, not the "
        "world-readable mode ordinary runtime state gets"
    )
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert trs.store_db_exposure() == []
