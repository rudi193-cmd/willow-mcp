"""The subject-consent gate, exercised end-to-end through _guarded.

Slice 3 threads a `subject_id` through the four subject-touching tools. These
tests drive the real MCP tool objects (so the whole _guarded pipeline runs: the
capability gate, then the subject gate) and prove the third check actually fires:

  - a call naming a non-owner subject with NO grant is denied, subject_consent_denied,
    *before* the tool body runs (no Postgres, no Nest DB needed to see the denial);
  - the same call passes the subject gate once a grant exists — it then fails for a
    mundane reason (postgres_unavailable / no Nest DB), which proves the gate opened;
  - a call with no subject_id is unaffected — the gate is inert, as designed.

The scope matters: lineage_record needs `person_inference`, not `kb_promotion` —
a grant for the wrong scope does not open the gate.
"""
import json

import pytest

from willow_mcp import server
from willow_mcp import subject_consent_binding as binding
from willow_mcp.db import Store
from willow_mcp.receipts import ReceiptLog
from willow_mcp.subject_consent import core


def _fn(tool):
    return getattr(tool, "fn", tool)


@pytest.fixture
def mk_app(tmp_path, monkeypatch):
    apps = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps))
    monkeypatch.delenv("WILLOW_OWNER_SUBJECT_ID", raising=False)
    monkeypatch.setattr(server, "_store", Store(str(tmp_path / "store")))
    monkeypatch.setattr(server, "_receipt_log", ReceiptLog(str(tmp_path / "r.db")))
    monkeypatch.setattr(server, "_buckets", {})

    def _mk(app_id, perms):
        d = apps / app_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({"permissions": perms}))
        return app_id

    return _mk


def _grant(subject_id, scope):
    core.grant(binding.store(), subject_id, scope, "guardian")


# ── knowledge_ingest (kb_promotion) ────────────────────────────────────────────

def test_knowledge_ingest_denies_non_owner_subject_without_grant(mk_app):
    app = mk_app("writer", ["knowledge_write"])
    out = _fn(server.knowledge_ingest)(app_id=app, content="x", subject_id="subj-1")
    assert out.get("code") == "subject_consent_denied"
    assert out["scope"] == "kb_promotion"


def test_knowledge_ingest_gate_opens_after_grant(mk_app):
    app = mk_app("writer", ["knowledge_write"])
    _grant("subj-1", "kb_promotion")
    out = _fn(server.knowledge_ingest)(app_id=app, content="x", subject_id="subj-1")
    # gate opened → reached the core write, which fails on its own terms
    # (no Postgres / unconfirmed schema in this env) — NOT on subject consent
    assert out.get("code") != "subject_consent_denied"
    assert "subject_consent" not in json.dumps(out)


def test_knowledge_ingest_inert_without_subject_id(mk_app):
    app = mk_app("writer", ["knowledge_write"])
    out = _fn(server.knowledge_ingest)(app_id=app, content="x")
    # no subject named → gate is a no-op → straight to the core write
    assert out.get("code") != "subject_consent_denied"
    assert "subject_consent" not in json.dumps(out)


# ── lineage_record (person_inference — a different, higher scope) ──────────────

def test_lineage_record_denies_without_person_inference_grant(mk_app):
    app = mk_app("historian", ["lineage_write"])
    out = _fn(server.lineage_record)(
        app_id=app, id="A1", title="t", rationale="why",
        evidence=["pr#1"], subject_id="subj-2",
    )
    assert out.get("code") == "subject_consent_denied"
    assert out["scope"] == "person_inference"


def test_lineage_record_wrong_scope_grant_does_not_open_gate(mk_app):
    app = mk_app("historian", ["lineage_write"])
    _grant("subj-2", "kb_promotion")  # wrong scope for this tool
    out = _fn(server.lineage_record)(
        app_id=app, id="A1", title="t", rationale="why",
        evidence=["pr#1"], subject_id="subj-2",
    )
    assert out.get("code") == "subject_consent_denied"


def test_lineage_record_gate_opens_with_right_scope(mk_app):
    app = mk_app("historian", ["lineage_write"])
    _grant("subj-2", "person_inference")
    out = _fn(server.lineage_record)(
        app_id=app, id="A1", title="t", rationale="why",
        evidence=["pr#1"], subject_id="subj-2",
    )
    # gate opened → the tool body ran (record succeeds or fails on its own terms,
    # but NOT on subject consent)
    assert (out.get("code") if isinstance(out, dict) else None) != "subject_consent_denied"


# ── nest_promote (kb_promotion) ────────────────────────────────────────────────

def test_nest_promote_denies_non_owner_without_grant(mk_app):
    app = mk_app("nester", ["nest_write"])
    out = _fn(server.nest_promote)(app_id=app, subject_id="subj-3")
    assert out.get("code") == "subject_consent_denied"


def test_nest_promote_gate_opens_after_grant(mk_app):
    app = mk_app("nester", ["nest_write"])
    _grant("subj-3", "kb_promotion")
    out = _fn(server.nest_promote)(app_id=app, subject_id="subj-3")
    # gate opened → reached the body, which finds no Nest DB
    assert out.get("code") != "subject_consent_denied"
    assert "no Nest DB" in out.get("error", "")


# ── owner-exemption end to end ─────────────────────────────────────────────────

def test_configured_owner_is_exempt(mk_app, monkeypatch):
    app = mk_app("writer", ["knowledge_write"])
    monkeypatch.setenv("WILLOW_OWNER_SUBJECT_ID", "the-owner")
    out = _fn(server.knowledge_ingest)(app_id=app, content="x", subject_id="the-owner")
    # owner's own data → no grant needed → straight through to the core write
    assert out.get("code") != "subject_consent_denied"
    assert "subject_consent" not in json.dumps(out)
