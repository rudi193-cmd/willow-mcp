"""#186 P2 — orchestrator write gate checks session attestation.

Real end-to-end round trip against a disposable GPG key, same pattern as
test_pgp_manifest_signing.py: attest-session signs a dedicated
`<session>.attest.json` sidecar (paths.session_attestation_path) holding only
the stable {app_id, session_id} identity, and orchestrator_write_denial then
requires that signature to still verify before dispatch_send/verify_handoff/
agent_clear/frank_append/envelope_apply run as app_id=willow.

#313: the sidecar is deliberately NOT the live `sessions/willow-{id}.json`
record dispatch.session_bind rewrites on every state change (session_enter,
dispatch_accept, session_handoff_write, agent_clear, ...) -- signing that
mutable record self-invalidated on the very next ordinary write, including
the closeout write meant to end the session. See
test_attestation_survives_session_bind_state_changes and
test_attestation_survives_session_handoff_write below.
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


def _attest(session_id):
    """Sign the identity sidecar the same way `willow-mcp attest-session` does,
    without going through the CLI's tty/Kart guard (exercised separately)."""
    import json as jsonlib
    from datetime import datetime, timezone

    attest_path = paths.session_attestation_path("willow", session_id)
    attest_path.parent.mkdir(parents=True, exist_ok=True)
    attest_path.write_text(
        jsonlib.dumps(
            {
                "format": "orchestrator_session_attestation_v1",
                "app_id": "willow",
                "session_id": session_id,
                "attested_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    ok, detail = pgp.sign_detached(attest_path)
    assert ok, detail
    return attest_path


def test_env_only_still_works_when_pgp_disabled(home, monkeypatch):
    """No WILLOW_PGP_FINGERPRINT set → interim env-only behavior, unchanged."""
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    assert hs.orchestrator_write_denial("willow", "dispatch_send", serve_mode=False) is None


def test_pgp_enabled_denies_without_any_session_id(home, pgp_env, monkeypatch):
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    reason = hs.orchestrator_write_denial("willow", "dispatch_send", serve_mode=False)
    assert reason is not None
    assert "orchestrator_session_attestation_missing" in reason


def test_pgp_enabled_denies_unattested_session(home, pgp_env, monkeypatch):
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    ds.session_enter("willow", "sess-1")  # writes sessions/willow-sess-1.json, unsigned
    reason = hs.orchestrator_write_denial(
        "willow", "dispatch_send", serve_mode=False, session_id="sess-1"
    )
    assert reason is not None
    assert "orchestrator_session_attestation_missing" in reason


def test_pgp_enabled_allows_attested_session(home, pgp_env, monkeypatch):
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    ds.session_enter("willow", "sess-2")
    _attest("sess-2")
    assert hs.orchestrator_write_denial(
        "willow", "dispatch_send", serve_mode=False, session_id="sess-2"
    ) is None


def test_tampered_attestation_sidecar_is_denied(home, pgp_env, monkeypatch):
    """Signature is bound to the sidecar's bytes -- editing the sidecar in place
    (same shape #183's tampered-manifest test used) must invalidate it, and the
    denial reason must say BAD signature, not 'never attested'."""
    import json

    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    ds.session_enter("willow", "sess-3")
    attest_path = _attest("sess-3")
    data = json.loads(attest_path.read_text())
    data["session_id"] = "sess-TAMPERED"
    attest_path.write_text(json.dumps(data))
    reason = hs.orchestrator_write_denial(
        "willow", "dispatch_send", serve_mode=False, session_id="sess-3"
    )
    assert reason is not None
    assert "orchestrator_session_attestation_invalid" in reason
    assert "orchestrator_session_attestation_missing" not in reason


def test_attestation_survives_session_bind_state_changes(home, pgp_env, monkeypatch):
    """#313 core regression: session_bind (via session_enter/dispatch_accept/
    agent_clear/...) rewrites sessions/willow-{id}.json -- including a fresh
    updated_at -- on every ordinary state change. That must no longer touch,
    let alone invalidate, the attestation."""
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    ds.session_enter("willow", "sess-4")
    _attest("sess-4")
    assert hs.orchestrator_write_denial(
        "willow", "dispatch_send", serve_mode=False, session_id="sess-4"
    ) is None

    # Rewrite the live session record directly, the way session_bind does on
    # every state transition (session_enter, dispatch_accept, agent_clear).
    ds.session_bind("willow", "sess-4", "", "idle")
    ds.session_bind("willow", "sess-4", "", "idle")

    assert hs.orchestrator_write_denial(
        "willow", "dispatch_send", serve_mode=False, session_id="sess-4"
    ) is None


def test_attestation_survives_session_handoff_write(home, pgp_env, monkeypatch):
    """#313 confirmed sequence: session_handoff_write is the closeout tool and
    itself calls session_bind at the end (dispatch.py), rewriting the session
    file's updated_at. Under the old design that self-invalidated the very
    attestation the closeout's own frank_append needed. It must not anymore."""
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    ds.session_enter("willow", "sess-5")
    _attest("sess-5")

    result = ds.session_handoff_write(
        "willow", "sess-5", narrative="closing out", summary="done"
    )
    assert "error" not in result

    reason = hs.orchestrator_write_denial(
        "willow", "frank_append", serve_mode=False, session_id="sess-5"
    )
    assert reason is None, reason


def test_serve_mode_bypasses_attestation_check(home, pgp_env, monkeypatch):
    """Serve mode trusts the confirmed OAuth binding alone -- unchanged by #186."""
    assert hs.orchestrator_write_denial(
        "willow", "dispatch_send", serve_mode=True, session_id=""
    ) is None


def test_specialist_write_never_attestation_gated(home, pgp_env, monkeypatch):
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


def test_attest_session_cli_writes_sidecar_not_live_session_file(home, pgp_env, monkeypatch):
    """#313: the CLI must not sign the live session record in place -- that's
    exactly the file dispatch.session_bind rewrites on every state change."""
    from willow_mcp import server

    class _Args:
        session_id = "sess-cli-4"

    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    monkeypatch.setattr(server.sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("WILLOW_IN_KART", raising=False)
    ds.session_enter("willow", "sess-cli-4")

    session_file = paths.session_path("willow", "sess-cli-4")
    session_sig = session_file.parent / f"{session_file.name}.sig"
    server._cmd_attest_session(_Args())

    assert not session_sig.exists(), (
        "attest-session must not detach-sign the live session record"
    )
    attest_sidecar = paths.session_attestation_path("willow", "sess-cli-4")
    assert attest_sidecar.is_file()
    assert (attest_sidecar.parent / f"{attest_sidecar.name}.sig").is_file()


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

    _attest("sess-gate-1")

    result = server.dispatch_send("willow", "hanuman", "# do the thing\n")
    assert "error" not in result or "attestation" not in result.get("error", "")
