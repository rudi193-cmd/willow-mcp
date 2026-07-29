"""CLI wiring for the subject-consent mutation seat.

`grant-consent` / `revoke-consent` expose the operator-terminal primitives in
`subject_consent_binding`; `consent-status` is their read-only counterpart. The
mutation subcommands must fail closed off an operator terminal (the sudo
invariant) and land a real grant on it. The read must work without one.
"""
from __future__ import annotations

import json
import subprocess
import sys
import types

import pytest

from willow_mcp import server
from willow_mcp import subject_consent_binding as scb
from willow_mcp.subject_consent import core


def _run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the CLI in a subprocess.

    A `None` value in `env` UNSETS that variable rather than passing it through.
    That matters because this inherits the parent environment, so an ambient
    variable can silently decide which branch of a gate the test exercises —
    `require_operator_terminal` checks WILLOW_IN_KART *before* the tty, so a run
    inside the Kart sandbox refuses for a different reason than the one the test
    names. A test whose meaning depends on where it runs is not pinning anything.
    """
    import os

    merged = {**os.environ, **(env or {})}
    merged = {k: v for k, v in merged.items() if v is not None}
    return subprocess.run(
        [sys.executable, "-m", "willow_mcp", *args],
        capture_output=True,
        text=True,
        env=merged,
        check=False,
    )


class _NullReceipts:
    def __init__(self):
        self.records = []

    def record(self, app_id, tool, outcome, detail=None):
        self.records.append((app_id, tool, outcome, detail))


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.delenv("WILLOW_OWNER_SUBJECT_ID", raising=False)
    monkeypatch.setattr(scb, "_receipts", _NullReceipts())
    return tmp_path


# ── fail-closed: mutation refused off an operator terminal ─────────────────────

#: `require_operator_terminal` has four refusal arms and checks them in order:
#: WILLOW_IN_KART, then isatty, then tty-verifiable, then tty-ownership. Each
#: test below pins WHICH arm it exercises, because the first one is set by the
#: ambient environment and would otherwise decide silently.
_NOT_IN_SANDBOX = {"WILLOW_IN_KART": None}


@pytest.mark.parametrize("subcommand", ["grant-consent", "revoke-consent"])
def test_consent_mutation_refused_without_operator_terminal(tmp_path, subcommand):
    """The tty arm. A subprocess has no interactive operator tty.

    WILLOW_IN_KART is cleared so this exercises the isatty check wherever it
    runs. Without that it passed outside a sandbox and failed inside one — not
    because the gate was wrong, but because a *different* arm of the same gate
    fired first and said so in different words.
    """
    out = _run(
        subcommand, "subj-1", "kb_promotion", "--by", "guardian",
        env={"WILLOW_HOME": str(tmp_path), **_NOT_IN_SANDBOX},
    )
    assert out.returncode == 1, out.stdout
    assert "operator terminal" in out.stderr.lower(), out.stderr


@pytest.mark.parametrize("subcommand", ["grant-consent", "revoke-consent"])
def test_consent_mutation_refused_inside_the_kart_sandbox(tmp_path, subcommand):
    """The sandbox arm, now on purpose.

    This is the branch a Kart run was hitting by accident. It is the stronger of
    the two — an agent draining tasks can allocate a pty and forge isatty(), but
    it cannot leave the sandbox it was launched in — so it deserves a test of its
    own rather than being reached by luck.
    """
    out = _run(
        subcommand, "subj-1", "kb_promotion", "--by", "guardian",
        env={"WILLOW_HOME": str(tmp_path), "WILLOW_IN_KART": "1"},
    )
    assert out.returncode == 1, out.stdout
    assert "kart sandbox" in out.stderr.lower(), out.stderr


# ── argparse fails closed on an unknown scope ──────────────────────────────────

def test_grant_consent_rejects_unknown_scope(tmp_path):
    out = _run(
        "grant-consent", "subj-1", "not_a_scope", "--by", "guardian",
        env={"WILLOW_HOME": str(tmp_path)},
    )
    assert out.returncode == 2  # argparse usage error
    assert "invalid choice" in out.stderr.lower()


# ── happy path (operator terminal simulated) ───────────────────────────────────

def test_grant_consent_records_and_status_reflects_it(home, monkeypatch, capsys):
    monkeypatch.setattr(scb, "_require_operator_terminal", lambda: None)

    server._cmd_grant_consent(
        types.SimpleNamespace(subject_id="subj-1", scope="kb_promotion", by="guardian")
    )
    granted = json.loads(capsys.readouterr().out)
    assert granted["status"] == "granted"
    assert granted["scope"] == "kb_promotion"
    assert granted["granted_by"] == "guardian"

    # the grant is real: the runtime gate now permits that subject + scope
    assert core.permitted(scb.store(), "subj-1", "kb_promotion") is True

    # consent-status (read-only) reflects it without an operator terminal
    server._cmd_consent_status(types.SimpleNamespace(subject_id="subj-1"))
    status = json.loads(capsys.readouterr().out)
    assert "kb_promotion" in status["granted_scopes"]
    assert status["scopes"]["kb_promotion"] is True
    assert status["is_owner"] is False
    assert any(d["action"] == "subject_consent_granted" for d in status["disclosures"])


def test_revoke_consent_flips_the_gate(home, monkeypatch, capsys):
    monkeypatch.setattr(scb, "_require_operator_terminal", lambda: None)

    server._cmd_grant_consent(
        types.SimpleNamespace(subject_id="subj-2", scope="person_inference", by="guardian")
    )
    capsys.readouterr()
    assert core.permitted(scb.store(), "subj-2", "person_inference") is True

    server._cmd_revoke_consent(
        types.SimpleNamespace(subject_id="subj-2", scope="person_inference", by="guardian")
    )
    revoked = json.loads(capsys.readouterr().out)
    assert revoked["status"] == "revoked"
    assert revoked["revoked_by"] == "guardian"
    assert core.permitted(scb.store(), "subj-2", "person_inference") is False


def test_consent_status_is_readonly_and_needs_no_terminal(home, capsys):
    # no monkeypatch of the operator terminal — a read must not require one
    server._cmd_consent_status(types.SimpleNamespace(subject_id="unknown-subject"))
    status = json.loads(capsys.readouterr().out)
    assert status["subject_id"] == "unknown-subject"
    assert status["granted_scopes"] == []
    assert status["disclosures"] == []
    assert set(status["scopes"]) == set(core.SCOPES)
