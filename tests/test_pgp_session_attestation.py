"""#186 P2 — orchestrator write gate checks session attestation.

Real end-to-end round trip against a disposable GPG key, same pattern as
test_pgp_manifest_signing.py: attest-session signs the live session file
session_enter(willow, ...) wrote, and orchestrator_write_denial then requires
that signature to still verify before dispatch_send/verify_handoff/agent_clear/
frank_append/envelope_apply run as app_id=willow.
"""
import os
import subprocess

import pytest

from willow_mcp import dispatch as ds
from willow_mcp import human_session as hs
from willow_mcp import paths, pgp


def _gen_key(gnupghome, name, email):
    batch = gnupghome / f"{name}.batch"
    batch.write_text(
        "%no-protection\n"
        "Key-Type: EDDSA\n"
        "Key-Curve: ed25519\n"
        f"Name-Real: {name}\n"
        f"Name-Email: {email}\n"
        "Expire-Date: 0\n"
        "%commit\n"
    )
    env = {**os.environ, "GNUPGHOME": str(gnupghome)}
    subprocess.run(
        ["gpg", "--batch", "--gen-key", str(batch)],
        env=env, check=True, capture_output=True, timeout=30,
    )


@pytest.fixture(scope="module")
def gpg_keypair(tmp_path_factory):
    gnupghome = tmp_path_factory.mktemp("gnupghome")
    _gen_key(gnupghome, "Willow Test Operator", "test@willow.invalid")
    env = {**os.environ, "GNUPGHOME": str(gnupghome)}
    out = subprocess.run(
        ["gpg", "--list-secret-keys", "--with-colons"],
        env=env, check=True, capture_output=True, text=True, timeout=10,
    )
    fpr = next(line.split(":")[9] for line in out.stdout.splitlines() if line.startswith("fpr"))
    return {"gnupghome": str(gnupghome), "fingerprint": fpr}


@pytest.fixture
def pgp_env(gpg_keypair, monkeypatch):
    monkeypatch.setenv("GNUPGHOME", gpg_keypair["gnupghome"])
    monkeypatch.setenv("WILLOW_PGP_FINGERPRINT", gpg_keypair["fingerprint"])


def test_env_only_still_works_when_pgp_disabled(home, monkeypatch):
    """No WILLOW_PGP_FINGERPRINT set → interim env-only behavior, unchanged."""
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    assert hs.orchestrator_write_denial("willow", "dispatch_send", serve_mode=False) is None


def test_pgp_enabled_denies_without_any_session_id(home, pgp_env, monkeypatch):
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    reason = hs.orchestrator_write_denial("willow", "dispatch_send", serve_mode=False)
    assert reason is not None
    assert "orchestrator_session_attestation_required" in reason


def test_pgp_enabled_denies_unattested_session(home, pgp_env, monkeypatch):
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    ds.session_enter("willow", "sess-1")  # writes sessions/willow-sess-1.json, unsigned
    reason = hs.orchestrator_write_denial(
        "willow", "dispatch_send", serve_mode=False, session_id="sess-1"
    )
    assert reason is not None
    assert "orchestrator_session_attestation_required" in reason


def test_pgp_enabled_allows_attested_session(home, pgp_env, monkeypatch):
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    ds.session_enter("willow", "sess-2")
    session_file = paths.session_path("willow", "sess-2")
    ok, detail = pgp.sign_detached(session_file)
    assert ok, detail
    assert hs.orchestrator_write_denial(
        "willow", "dispatch_send", serve_mode=False, session_id="sess-2"
    ) is None


def test_tampered_session_after_attestation_is_denied(home, pgp_env, monkeypatch):
    """Signature is bound to file bytes -- editing the session file in place
    (same shape #183's tampered-manifest test used) must invalidate it."""
    import json

    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    ds.session_enter("willow", "sess-3")
    session_file = paths.session_path("willow", "sess-3")
    ok, _ = pgp.sign_detached(session_file)
    assert ok
    data = json.loads(session_file.read_text())
    data["dispatch_id"] = "TAMPERED1"
    session_file.write_text(json.dumps(data))
    reason = hs.orchestrator_write_denial(
        "willow", "dispatch_send", serve_mode=False, session_id="sess-3"
    )
    assert reason is not None
    assert "orchestrator_session_attestation_required" in reason


def test_serve_mode_bypasses_attestation_check(home, pgp_env, monkeypatch):
    """Serve mode trusts the confirmed OAuth binding alone -- unchanged by #186."""
    assert hs.orchestrator_write_denial(
        "willow", "dispatch_send", serve_mode=True, session_id=""
    ) is None


def test_specialist_write_never_attestation_gated(home, pgp_env, monkeypatch):
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    assert hs.orchestrator_write_denial(
        "hanuman", "dispatch_send", serve_mode=False, session_id=""
    ) is None


# ── attest-session CLI ───────────────────────────────────────────────────────

def test_attest_session_cli_requires_operator_terminal(home, pgp_env, monkeypatch):
    from willow_mcp import server

    class _Args:
        session_id = "sess-cli-1"

    ds.session_enter("willow", "sess-cli-1")
    monkeypatch.setattr(server.sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        server._cmd_attest_session(_Args())


def test_attest_session_cli_refuses_when_pgp_not_enabled(home, monkeypatch):
    from willow_mcp import server

    class _Args:
        session_id = "sess-cli-2"

    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    monkeypatch.setattr(server.sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("WILLOW_IN_KART", raising=False)
    ds.session_enter("willow", "sess-cli-2")
    with pytest.raises(SystemExit):
        server._cmd_attest_session(_Args())


def test_attest_session_cli_refuses_when_session_never_entered(home, pgp_env, monkeypatch):
    from willow_mcp import server

    class _Args:
        session_id = "sess-never-entered"

    monkeypatch.setattr(server.sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("WILLOW_IN_KART", raising=False)
    with pytest.raises(SystemExit):
        server._cmd_attest_session(_Args())


def test_attest_session_cli_signs_and_gate_then_trusts_it(home, pgp_env, monkeypatch):
    from willow_mcp import server

    class _Args:
        session_id = "sess-cli-3"

    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    monkeypatch.setattr(server.sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("WILLOW_IN_KART", raising=False)
    ds.session_enter("willow", "sess-cli-3")
    server._cmd_attest_session(_Args())
    assert hs.orchestrator_write_denial(
        "willow", "dispatch_send", serve_mode=False, session_id="sess-cli-3"
    ) is None


# ── server._gate threading: session_enter records the current session ───────

def test_gate_reads_back_session_recorded_by_session_enter(home, pgp_env, monkeypatch):
    """End-to-end through the MCP tool wrapper, not the bare dispatch module:
    session_enter(app_id=willow) records session_id in server-process state,
    and _gate reads it back for the next orchestrator-write call in the same
    process -- callers of dispatch_send etc. never pass session_id themselves."""
    import json

    from willow_mcp import server

    apps = home / "mcp_apps" / "willow"
    apps.mkdir(parents=True)
    manifest_path = apps / "manifest.json"
    manifest_path.write_text(json.dumps({"permissions": ["orchestrator"]}))
    ok, detail = pgp.sign_detached(manifest_path)
    assert ok, detail

    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    server._set_orchestrator_session("")  # isolate from any earlier test in this process
    server.session_enter("willow", "sess-gate-1")
    assert server._current_orchestrator_session() == "sess-gate-1"

    session_file = paths.session_path("willow", "sess-gate-1")
    ok, detail = pgp.sign_detached(session_file)
    assert ok, detail

    result = server.dispatch_send("willow", "hanuman", "# do the thing\n")
    assert "error" not in result or "attestation" not in result.get("error", "")
