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
    import os

    merged = {**os.environ, **(env or {})}
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

def test_grant_consent_refused_without_operator_terminal(tmp_path):
    # a subprocess has no interactive operator tty → require_operator_terminal fires
    out = _run(
        "grant-consent", "subj-1", "kb_promotion", "--by", "guardian",
        env={"WILLOW_HOME": str(tmp_path)},
    )
    assert out.returncode == 1, out.stdout
    assert "operator terminal" in out.stderr.lower()


def test_revoke_consent_refused_without_operator_terminal(tmp_path):
    out = _run(
        "revoke-consent", "subj-1", "kb_promotion", "--by", "guardian",
        env={"WILLOW_HOME": str(tmp_path)},
    )
    assert out.returncode == 1, out.stdout
    assert "operator terminal" in out.stderr.lower()


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
