"""The Commitment Membrane MCP surface — the front door on the WO-2 engine.

The ledger/persistence engine landed on master with unit tests but no MCP tools.
These drive the four new tools (commitment_ingest/acknowledge/surface/list) end to
end through the real _guarded pipeline, and assert the membrane's three disciplines
survive the trip across the tool boundary:

  - receipt-not-recording — an event body handed to ingest is NEVER persisted and
    never appears in a read tool's output;
  - states-not-deletions — a cancel is a WITHDRAWN state and a move keeps the old
    time in history; nothing is dropped;
  - no new authority — there is no tool that writes the calendar back (the read
    tools are gated apart from the write tools, and neither can mutate the source).
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
    monkeypatch.setattr(server, "_store", Store(str(tmp_path / "store")))
    monkeypatch.setattr(server, "_receipt_log", ReceiptLog(str(tmp_path / "r.db")))
    monkeypatch.setattr(server, "_buckets", {})

    def _mk(app_id, perms):
        d = apps / app_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({"permissions": perms}))
        return app_id

    return _mk


def _ev(uid, title, start, **kw):
    return {"uid": uid, "title": title, "start": start, **kw}


# ── ingest + list: the round trip, facts only ─────────────────────────────────

def test_ingest_then_list(mk_app):
    app = mk_app("jarvis", ["commitment_write", "commitment_read"])
    out = _fn(server.commitment_ingest)(app_id=app, events=[
        _ev("e1", "Dentist", "2026-07-21T15:00:00"),
        _ev("e2", "Standup", "2026-07-21T09:00:00", end="2026-07-21T09:15:00"),
    ])
    assert out["status"] == "ok" and out["ingested"] == 2
    listed = _fn(server.commitment_list)(app_id=app)
    assert listed["count"] == 2
    # sorted by when → Standup (09:00) first
    assert [c["title"] for c in listed["commitments"]] == ["Standup", "Dentist"]


def test_ingest_without_events_is_transport_unwired(mk_app):
    app = mk_app("jarvis", ["commitment_write"])
    out = _fn(server.commitment_ingest)(app_id=app)
    assert out["status"] == "transport_unwired"
    assert out["ingested"] == 0


def test_ingest_malformed_event(mk_app):
    app = mk_app("jarvis", ["commitment_write"])
    out = _fn(server.commitment_ingest)(app_id=app, events=[{"title": "no uid or start"}])
    assert "malformed events" in out.get("error", "")


# ── discipline 1: receipt-not-recording (body never persisted) ────────────────

def test_body_is_never_persisted_or_returned(mk_app):
    app = mk_app("jarvis", ["commitment_write", "commitment_read"])
    _fn(server.commitment_ingest)(app_id=app, events=[
        _ev("e1", "Therapy", "2026-07-21T15:00:00",
            body="SENSITIVE NOTES — diagnosis, address, phone"),
    ])
    # not in the read-tool output
    listed = _fn(server.commitment_list)(app_id=app)
    blob = json.dumps(listed)
    assert "SENSITIVE" not in blob and "body" not in listed["commitments"][0]
    # not in the raw SOIL record either — the persistence-boundary guard held
    raw = server._store.all(server._COMMITMENT_COLLECTION)
    assert raw and "SENSITIVE" not in json.dumps(raw)
    for rec in raw:
        for forbidden in ("body", "notes", "description", "location", "raw"):
            assert forbidden not in rec


# ── discipline 2: states-not-deletions ────────────────────────────────────────

def test_cancel_is_a_withdrawn_state_not_a_delete(mk_app):
    app = mk_app("jarvis", ["commitment_write", "commitment_read"])
    _fn(server.commitment_ingest)(app_id=app, events=[_ev("e1", "Lunch", "2026-07-21T12:00:00")])
    _fn(server.commitment_ingest)(app_id=app, events=[
        _ev("e1", "Lunch", "2026-07-21T12:00:00", cancelled=True)])
    listed = _fn(server.commitment_list)(app_id=app)
    assert listed["count"] == 1  # still there, not deleted
    c = listed["commitments"][0]
    assert c["state"] == "WITHDRAWN"
    assert c["history_len"] >= 2  # created + cancelled


def test_move_keeps_old_time_in_history(mk_app):
    app = mk_app("jarvis", ["commitment_write", "commitment_read"])
    _fn(server.commitment_ingest)(app_id=app, events=[_ev("e1", "Call", "2026-07-21T10:00:00")])
    out = _fn(server.commitment_ingest)(app_id=app, events=[_ev("e1", "Call", "2026-07-21T14:00:00")])
    assert out["changes"].get("move") == 1
    c = _fn(server.commitment_list)(app_id=app)["commitments"][0]
    assert c["state"] == "ACTIVE" and c["when"].startswith("2026-07-21T14:00")
    assert c["history_len"] >= 2


# ── acknowledge + the dew rule ────────────────────────────────────────────────

def test_surface_mismatch_then_acknowledge_clears_it(mk_app):
    app = mk_app("jarvis", ["commitment_write", "commitment_read"])
    # a moved event is unacknowledged → surfaces as a mismatch
    _fn(server.commitment_ingest)(app_id=app, events=[_ev("e1", "Call", "2026-07-21T10:00:00")])
    _fn(server.commitment_ingest)(app_id=app, events=[_ev("e1", "Call", "2026-07-21T14:00:00")])
    surf = _fn(server.commitment_surface)(app_id=app, now="2026-07-20T00:00:00")
    assert any(s["kind"] == "mismatch" for s in surf["surfacings"])
    # acknowledge → the halves match again
    ack = _fn(server.commitment_acknowledge)(app_id=app, uid="e1")
    assert ack["status"] == "ok"
    surf2 = _fn(server.commitment_surface)(app_id=app, now="2026-07-20T00:00:00")
    assert not any(s["kind"] == "mismatch" for s in surf2["surfacings"])


def test_acknowledge_unknown_uid(mk_app):
    app = mk_app("jarvis", ["commitment_write"])
    out = _fn(server.commitment_acknowledge)(app_id=app, uid="nope")
    assert out.get("error") == "unknown_uid"


def test_surface_imminent(mk_app):
    app = mk_app("jarvis", ["commitment_write", "commitment_read"])
    _fn(server.commitment_ingest)(app_id=app, events=[_ev("e1", "Boarding", "2026-07-21T12:00:00")])
    _fn(server.commitment_acknowledge)(app_id=app, uid="e1")  # clear the first-sight mismatch
    surf = _fn(server.commitment_surface)(app_id=app, now="2026-07-21T11:50:00", lead_minutes=15)
    kinds = {s["kind"] for s in surf["surfacings"]}
    assert "imminent" in kinds
    # title + time only, never a body
    assert all("body" not in s["fact"].lower() for s in surf["surfacings"])


def test_surface_conflict(mk_app):
    app = mk_app("jarvis", ["commitment_write", "commitment_read"])
    _fn(server.commitment_ingest)(app_id=app, events=[
        _ev("a", "A", "2026-07-21T10:00:00", end="2026-07-21T11:00:00"),
        _ev("b", "B", "2026-07-21T10:30:00", end="2026-07-21T11:30:00"),
    ])
    surf = _fn(server.commitment_surface)(app_id=app, now="2026-07-20T00:00:00")
    assert any(s["kind"] == "conflict" for s in surf["surfacings"])


def test_list_state_filter_validation(mk_app):
    app = mk_app("jarvis", ["commitment_read"])
    out = _fn(server.commitment_list)(app_id=app, state="bogus")
    assert "ACTIVE" in out.get("error", "")


# ── discipline 3 / gate: read and write are separately gated ──────────────────

def test_read_group_cannot_write(mk_app):
    app = mk_app("reader", ["commitment_read"])  # read only
    out = _fn(server.commitment_ingest)(app_id=app, events=[_ev("e1", "x", "2026-07-21T10:00:00")])
    assert "gate denied" in out.get("error", "")


def test_write_group_cannot_read(mk_app):
    app = mk_app("writer", ["commitment_write"])  # write only
    out = _fn(server.commitment_list)(app_id=app)
    assert "gate denied" in out.get("error", "")


def test_unpermitted_app_denied(mk_app):
    app = mk_app("stranger", ["store_read"])
    out = _fn(server.commitment_surface)(app_id=app)
    assert "gate denied" in out.get("error", "")
