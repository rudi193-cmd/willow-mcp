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
    """The attested host — WILLOW_HUMAN_ORCHESTRATOR=1 on the SERVER's env, which
    no tool call can reach — is the only thing that produces by_human."""
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    app = mk_app("willow", ["human_loop_write", "human_loop_read"])
    rec = _fn(server.human_attestation_create)(app_id=app, subject_id="ATOM1")
    assert rec["attested_by"] == "willow"
    assert rec["by_human"] is True


def test_claiming_the_willow_app_id_does_not_produce_by_human(mk_app):
    """Passing app_id='willow' from an unattested stdio host must NOT mint a
    by_human record.

    In stdio mode app_id is a caller-supplied tool-call argument, so a string
    compare against it records what the caller *called itself*, not who it is.
    The record must be attributed to willow (that is the identity it claimed and
    the receipt should say so) but must not carry the operator's signature.
    """
    app = mk_app("willow", ["human_loop_write", "human_loop_read"])
    rec = _fn(server.human_attestation_create)(app_id=app, subject_id="ATOM_FORGE")
    assert rec["attested_by"] == "willow"
    assert rec["by_human"] is False


def test_forged_willow_seat_does_not_satisfy_the_human_gate(mk_app):
    """The end-to-end property the by_human flag exists to provide: an agent that
    names itself willow cannot make has_attestation(require_human=True) true."""
    from willow_mcp import human_loop
    app = mk_app("willow", ["human_loop_write"])
    _fn(server.human_attestation_create)(app_id=app, subject_id="ATOM_FORGE2")
    # the attestation is real…
    assert human_loop.has_attestation(server._store, subject_id="ATOM_FORGE2") is True
    # …and it does not clear the human gate
    assert human_loop.has_attestation(
        server._store, subject_id="ATOM_FORGE2", require_human=True) is False


def test_by_human_actually_depends_on_the_host_attestation(mk_app, monkeypatch):
    """Mutation guard on the two tests above.

    The bug this replaces was not the forgery — it was that
    test_human_seat_attestation_is_marked_by_human set WILLOW_HUMAN_ORCHESTRATOR=1
    and passed identically without it, so a green suite asserted an invariant that
    did not exist. This pins the *difference*: same app_id, same call, opposite
    by_human. It fails if the env var ever stops being load-bearing again.
    """
    app = mk_app("willow", ["human_loop_write", "human_loop_read"])

    monkeypatch.delenv("WILLOW_HUMAN_ORCHESTRATOR", raising=False)
    unattested = _fn(server.human_attestation_create)(app_id=app, subject_id="ATOM_A")

    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    attested = _fn(server.human_attestation_create)(app_id=app, subject_id="ATOM_B")

    assert unattested["attested_by"] == attested["attested_by"] == "willow"
    assert unattested["by_human"] is False
    assert attested["by_human"] is True


def test_guarded_hands_the_tool_body_the_gate_resolved_app_id(mk_app, monkeypatch):
    """Pins the cross-module assumption the serve arm of by_human_attested rests on.

    `by_human_attested(app_id, serve_mode=True)` returns True *unconditionally*.
    That is only safe because the app_id reaching a tool body in serve mode is
    not the caller's: `_guarded` overwrites it with the identity `_gate` resolved
    from the verified OAuth binding. If that substitution is ever refactored
    away, the serve arm silently becomes an unconditional True — this fix undone,
    with the docstring still claiming otherwise, which is precisely the shape of
    the defect being repaired here.

    This stubs `_gate` outright, so it pins the substitution alone and stays
    true whatever the gate decides. The serve arm it exists to protect is now
    also driven for real — real OAuth session, real confirmed binding, real
    gate — in test_serve_mode_gate.py, which enters serve mode through the
    `server._serve_mode()` accessor rather than sys.argv.
    """
    mk_app("willow", ["human_loop_write", "human_loop_read"])
    caller = mk_app("hanuman", ["human_loop_write", "human_loop_read"])
    monkeypatch.setattr(server, "_gate", lambda app_id, tool_name: ("willow", None))

    rec = _fn(server.human_attestation_create)(app_id=caller, subject_id="ATOM_SUB")

    # "hanuman" here would mean the body read the caller's argument instead of
    # the gate's answer — the premise of the serve arm gone.
    assert rec["attested_by"] == "willow"


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
