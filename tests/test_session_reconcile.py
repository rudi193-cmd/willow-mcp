"""Session reconciliation — check-out declare-vs-did (willow-gate seam Phase 4 / H3).

The agent declares at check-out which tool CLASSES it exercised; the server diffs
that against the receipt log (the ground truth it cannot feed). Privileged
discrepancies make the session unclean; read-level over/under-reporting is noise.
"""
import json
import uuid

import pytest

from willow_mcp import server, agent_registry as reg, session_binder as sb
from willow_mcp import tier_policy as tp
from willow_mcp.db import Store
from willow_mcp.receipts import ReceiptLog


# ── pure reconcile() ──────────────────────────────────────────────────────────

def _exit(tools, **kw):
    d = {"tools": list(tools), "pass_count": 1, "fail_count": 0, "drift": 0, "state_hash": "h"}
    d.update(kw)
    return d


def test_clean_when_exit_matches_receipts():
    r = sb.reconcile({"tools": [tp.READ, tp.WRITE]},
                     _exit([tp.READ, tp.WRITE]),
                     ["store_get", "store_put"])
    assert r["clean"]
    assert r["actual_classes"] == [tp.READ, tp.WRITE]


def test_claimed_not_done_makes_unclean():
    # Agent claims it executed, but no execute receipt backs it — the H3 catch.
    r = sb.reconcile({"tools": [tp.READ, tp.EXECUTE]},
                     _exit([tp.READ, tp.EXECUTE]),
                     ["store_get"])
    assert not r["clean"]
    assert r["claimed_not_done"] == [tp.EXECUTE]


def test_privileged_use_not_declared_makes_unclean():
    # Receipts show a write; the agent declared only read at both ends.
    r = sb.reconcile({"tools": [tp.READ]},
                     _exit([tp.READ]),
                     ["store_get", "store_put"])
    assert not r["clean"]
    assert tp.WRITE in r["done_not_claimed"]
    assert tp.WRITE in r["beyond_entry"]


def test_read_level_mismatch_is_noise_not_unclean():
    # Used read (session_enter etc.) without declaring it — surfaced, still clean.
    r = sb.reconcile({"tools": [tp.WRITE]}, _exit([tp.WRITE]),
                     ["store_get", "store_put"])
    assert r["clean"]
    assert r["done_not_claimed"] == [tp.READ]


def test_self_report_is_echoed_not_judged():
    r = sb.reconcile({"tools": [tp.READ]}, _exit([tp.READ], pass_count=9, drift=3),
                     ["store_get"])
    assert r["self_report"] == {"pass_count": 9, "fail_count": 0, "drift": 3, "state_hash": "h"}


# ── check_out lifecycle ───────────────────────────────────────────────────────

@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.delenv("WILLOW_MCP_APPS_ROOT", raising=False)
    return tmp_path


def _bind(binder, app_id, trust, tools=("read",)):
    secret = bytes.fromhex(reg.register_agent(app_id, trust)["secret_hex"])
    h = {"agent_id": app_id, "agent_name": app_id, "last_gate": "t",
         "pass_count": 0, "fail_count": 0, "drift": 0, "nonce": uuid.uuid4().hex,
         "trust_level": trust, "timestamp": 1000, "tools": list(tools),
         "state_hash": "s0", "reserved": 0, "signature": "0" * 64}
    h["signature"] = sb.expected_header_sig(secret, h)
    return secret, binder.check_in(h)["session_id"]


def test_check_out_drops_the_session(home):
    b = sb.SessionBinder()
    _, sid = _bind(b, "op", 3)
    assert b.session_started_ts(sid) is not None
    b.check_out(sid, _exit(["read"]), ["store_get"])
    assert b.session_started_ts(sid) is None            # gone — nonce set freed


def test_check_out_unknown_session_raises(home):
    b = sb.SessionBinder()
    with pytest.raises(sb.BindError):
        b.check_out("nope", _exit(["read"]), [])


def test_check_out_rejects_malformed_exit_tools(home):
    b = sb.SessionBinder()
    _, sid = _bind(b, "op", 3)
    with pytest.raises(sb.BindError):
        b.check_out(sid, {"tools": "read"}, [])          # not a list


def test_check_out_uses_entry_declaration_for_scope(home):
    b = sb.SessionBinder()
    _, sid = _bind(b, "op", 3, tools=["read"])           # entry declared read only
    r = b.check_out(sid, _exit([tp.READ, tp.EXECUTE]), ["store_get", "task_submit"])
    assert tp.EXECUTE in r["beyond_entry"] and not r["clean"]


# ── ReceiptLog.since ──────────────────────────────────────────────────────────

def test_since_windows_by_time_and_scopes_by_app(tmp_path):
    log = ReceiptLog(str(tmp_path / "r.db"))
    log.record("me", "store_get", "ok", None)
    cut = log.tail("me")[0]["ts"]
    log.record("me", "store_put", "ok", None)
    log.record("other", "store_put", "ok", None)
    rows = log.since("me", cut)
    assert [r["tool"] for r in rows] == ["store_get", "store_put"]   # oldest-first, mine only


def test_since_filters_by_outcome(tmp_path):
    log = ReceiptLog(str(tmp_path / "r.db"))
    log.record("me", "store_get", "ok", None)
    log.record("me", "store_put", "denied", None)
    rows = log.since("me", "0000", outcome="ok")
    assert [r["tool"] for r in rows] == ["store_get"]


# ── end-to-end tool ───────────────────────────────────────────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "apps"))
    monkeypatch.delenv("WILLOW_MCP_ENFORCE_BINDING", raising=False)
    monkeypatch.setattr(server, "_store", Store(str(tmp_path / "store")))
    monkeypatch.setattr(server, "_receipt_log", ReceiptLog(str(tmp_path / "r.db")))
    monkeypatch.setattr(server, "_binder", sb.SessionBinder())

    def _manifest(app_id, perms=("full_access",)):
        d = tmp_path / "apps" / app_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({"permissions": list(perms)}))
        return app_id

    return _manifest


def _fn(tool):
    return getattr(tool, "fn", tool)


def test_reconcile_tool_clean_path(env):
    env("worker")
    _, sid = _bind(server._binder, "worker", 3, tools=["read", "write"])
    # simulate work the receipt log would have recorded
    server._receipt_log.record("worker", "store_get", "ok", None)
    server._receipt_log.record("worker", "store_put", "ok", None)
    out = _fn(server.session_reconcile)(
        app_id="worker", session_id=sid, exit_declaration=_exit([tp.READ, tp.WRITE]))
    assert out["clean"] is True
    assert server._binder.session_started_ts(sid) is None          # closed
    assert any(r["outcome"] == "reconciled" for r in server._receipt_log.tail("worker"))


def test_reconcile_tool_flags_false_execute_claim(env):
    env("worker")
    _, sid = _bind(server._binder, "worker", 3, tools=["read", "execute"])
    server._receipt_log.record("worker", "store_get", "ok", None)   # only a read ran
    out = _fn(server.session_reconcile)(
        app_id="worker", session_id=sid, exit_declaration=_exit([tp.READ, tp.EXECUTE]))
    assert out["clean"] is False and out["claimed_not_done"] == [tp.EXECUTE]
    assert any(r["outcome"] == "reconcile_discrepancy" for r in server._receipt_log.tail("worker"))


def test_reconcile_tool_without_session_errors(env):
    env("worker")
    out = _fn(server.session_reconcile)(
        app_id="worker", session_id="ghost", exit_declaration=_exit([tp.READ]))
    assert out["error"] == "no_live_session"


def test_reconcile_tool_only_counts_calls_that_ran(env):
    env("worker")
    _, sid = _bind(server._binder, "worker", 3, tools=["read"])
    server._receipt_log.record("worker", "store_put", "denied", None)   # attempted, blocked
    # A denied write must NOT count as actual write use — the agent didn't do it.
    out = _fn(server.session_reconcile)(
        app_id="worker", session_id=sid, exit_declaration=_exit([tp.READ]))
    assert out["clean"] is True and tp.WRITE not in out["actual_classes"]
