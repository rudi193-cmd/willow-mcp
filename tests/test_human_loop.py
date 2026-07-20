"""human_loop — the human-in-the-loop queue + attestation port, through MCP.

Driven through the real _guarded pipeline over the SOIL store. The load-bearing
property is the anti-forgery one: the attester of an attestation is the CALLER's
identity, never a free parameter, and `by_human` is true only for the
human-orchestrator seat — so an agent cannot write a record claiming the operator
signed something.
"""
import json

import pytest

from willow_mcp import server
from willow_mcp.db import Store
from willow_mcp.receipts import ReceiptLog


def _fn(tool):
    return getattr(tool, "fn", tool)


@pytest.fixture
def mk_app(tmp_path, monkeypatch):
    apps = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps))
    monkeypatch.delenv("WILLOW_HUMAN_ORCHESTRATOR", raising=False)
    monkeypatch.setattr(server, "_store", Store(str(tmp_path / "store")))
    monkeypatch.setattr(server, "_receipt_log", ReceiptLog(str(tmp_path / "r.db")))
    monkeypatch.setattr(server, "_buckets", {})

    def _mk(app_id, perms):
        d = apps / app_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({"permissions": perms}))
        return app_id

    return _mk


# ── the queue: enqueue / list / resolve ───────────────────────────────────────

def test_enqueue_then_list(mk_app):
    app = mk_app("agent", ["human_loop_write", "human_loop_read"])
    item = _fn(server.human_required_enqueue)(
        app_id=app, kind="review", title="Check this migration", priority="high")
    assert item["status"] == "open" and item["source_agent"] == "agent"
    out = _fn(server.human_required_list)(app_id=app)
    assert out["count"] == 1
    assert out["stats"]["open"] == 1


def test_enqueue_bad_kind(mk_app):
    app = mk_app("agent", ["human_loop_write"])
    out = _fn(server.human_required_enqueue)(app_id=app, kind="nonsense", title="x")
    assert "invalid kind" in out.get("error", "")


def test_resolve_updates_in_place_not_deleted(mk_app):
    app = mk_app("agent", ["human_loop_write", "human_loop_read"])
    item = _fn(server.human_required_enqueue)(app_id=app, kind="consent", title="Approve egress")
    res = _fn(server.human_required_resolve)(
        app_id=app, item_id=item["id"], status="dismissed", note="not now")
    assert res["status"] == "dismissed" and res["resolved_by"] == "agent" and res["note"] == "not now"
    # still present (states-not-deletions), just not in the default 'open' view
    assert _fn(server.human_required_list)(app_id=app)["count"] == 0
    allq = _fn(server.human_required_list)(app_id=app, status="")
    assert allq["count"] == 1 and allq["stats"]["dismissed"] == 1


def test_resolve_unknown_item(mk_app):
    app = mk_app("agent", ["human_loop_write"])
    out = _fn(server.human_required_resolve)(app_id=app, item_id="nope")
    assert out.get("error") == "unknown_item"


def test_resolve_bad_status(mk_app):
    app = mk_app("agent", ["human_loop_write"])
    item = _fn(server.human_required_enqueue)(app_id=app, kind="review", title="x")
    out = _fn(server.human_required_resolve)(app_id=app, item_id=item["id"], status="deleted")
    assert "invalid status" in out.get("error", "")


# ── attestation ───────────────────────────────────────────────────────────────

def test_attestation_create_and_list(mk_app):
    app = mk_app("agent", ["human_loop_write", "human_loop_read"])
    rec = _fn(server.human_attestation_create)(
        app_id=app, subject_id="ATOM123", statement="looks right")
    assert rec["status"] == "attested" and rec["subject_id"] == "ATOM123"
    out = _fn(server.human_attestation_list)(app_id=app, subject_id="ATOM123")
    assert out["count"] == 1


def test_attestation_bad_subject_type(mk_app):
    app = mk_app("agent", ["human_loop_write"])
    out = _fn(server.human_attestation_create)(
        app_id=app, subject_id="X", subject_type="wormhole")
    assert "invalid subject_type" in out.get("error", "")


# ── the anti-forgery property (the reason for the port's departure) ───────────

def test_agent_attestation_is_attributed_to_itself_not_forged(mk_app):
    """There is no attested_by parameter — an agent's attestation records the agent,
    with by_human False. It cannot claim to be the operator."""
    app = mk_app("hanuman", ["human_loop_write", "human_loop_read"])
    rec = _fn(server.human_attestation_create)(app_id=app, subject_id="ATOM1")
    assert rec["attested_by"] == "hanuman"
    assert rec["by_human"] is False


def test_human_seat_attestation_is_marked_by_human(mk_app, monkeypatch):
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    app = mk_app("willow", ["human_loop_write", "human_loop_read"])
    rec = _fn(server.human_attestation_create)(app_id=app, subject_id="ATOM1")
    assert rec["attested_by"] == "willow"
    assert rec["by_human"] is True


def test_has_attestation_require_human_gates_out_agent_signoff(mk_app):
    from willow_mcp import human_loop
    app = mk_app("hanuman", ["human_loop_write"])  # an agent attests
    _fn(server.human_attestation_create)(app_id=app, subject_id="ATOM9")
    # a plain attestation exists…
    assert human_loop.has_attestation(server._store, subject_id="ATOM9") is True
    # …but it does NOT satisfy the human gate — an agent cannot sign as a human
    assert human_loop.has_attestation(server._store, subject_id="ATOM9", require_human=True) is False


# ── gate split ────────────────────────────────────────────────────────────────

def test_read_group_cannot_write(mk_app):
    app = mk_app("reader", ["human_loop_read"])
    out = _fn(server.human_required_enqueue)(app_id=app, kind="review", title="x")
    assert "gate denied" in out.get("error", "")


def test_write_group_cannot_read(mk_app):
    app = mk_app("writer", ["human_loop_write"])
    out = _fn(server.human_attestation_list)(app_id=app)
    assert "gate denied" in out.get("error", "")
