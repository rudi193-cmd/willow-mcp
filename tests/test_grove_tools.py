"""Tests for willow_mcp.grove_tools — the 20 Grove MCP tools.

Registers a fresh MCPServer and drives tools through `call_tool`, the same
pattern tests/test_mai_tools.py uses. `db.get_pg` is monkeypatched to a fake
connection (tests/test_grove.py's style) rather than touching live Postgres.
Covers: a read returns rows with datetimes serialized, a write issues the
right INSERT carrying the resolved grove_sender, gate deny/allow, and
grove_get_identity.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from willow_mcp import grove, grove_tools


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.description = None
        self.rowcount = 0
        self._rows = []

    def execute(self, sql, params=None):
        self._conn.calls.append((sql, params))
        cols, rows, rowcount = self._conn._pop_response()
        self.description = [(c,) for c in cols] if cols is not None else None
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _FakePg:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def cursor(self):
        return _FakeCursor(self)

    def _pop_response(self):
        if not self._responses:
            return (None, [], 0)
        return self._responses.pop(0)


def _now():
    return datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)


def _register():
    from mcp.server.mcpserver import MCPServer

    m = MCPServer("test-grove")
    grove_tools.register(m)
    return m


def _blocks(m, name, args):
    """Every content block from a tool call, JSON-decoded.

    The MCP SDK emits ONE TextContent per top-level list element for a
    list-returning tool (an empty list -> zero blocks, a one-item list -> one
    block whose text is that single item's JSON object) and exactly one block
    holding the whole object for a dict-returning tool — the wire shape does
    not distinguish "a list of one dict" from "a dict", so callers use
    `_call_list`/`_call_dict` below to say which they expect, rather than
    guessing from the response.
    """
    result = asyncio.run(m.call_tool(name, args))
    return [json.loads(c.text) for c in result.content if hasattr(c, "text")]


def _call_list(m, name, args):
    """For tools whose declared return type is list[...]."""
    return _blocks(m, name, args)


def _call_dict(m, name, args):
    """For tools whose declared return type is dict."""
    blocks = _blocks(m, name, args)
    assert len(blocks) == 1, f"expected exactly one content block, got {blocks!r}"
    return blocks[0]


_APP = "grovetest"


@pytest.fixture(autouse=True)
def granted_app(tmp_path, monkeypatch):
    apps_root = tmp_path / "mcp_apps"
    app_dir = apps_root / _APP
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["grove_read", "grove_write"]})
    )
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    return apps_root


@pytest.fixture
def ungranted_app(tmp_path, monkeypatch):
    apps_root = tmp_path / "mcp_apps"
    app_dir = apps_root / "noaccess"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(json.dumps({"permissions": ["store_read"]}))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    return "noaccess"


def test_registry_lists_twenty_grove_tools():
    m = _register()
    names = [t.name for t in asyncio.run(m.list_tools()) if t.name.startswith("grove_")]
    assert len(names) == 20
    assert "grove_send_message" in names
    assert "grove_agents" in names
    assert "grove_fleet_status" in names
    assert "grove_human_required" in names


# ── gate: deny without the group, allow with it ─────────────────────────────

def test_gate_denies_read_tool_without_grove_read_group(ungranted_app):
    m = _register()
    out = _call_list(m, "grove_list_channels", {"app_id": ungranted_app})
    assert "error" in out[0]
    assert "gate denied" in out[0]["error"]


def test_gate_denies_write_tool_without_grove_write_group(tmp_path, monkeypatch):
    apps_root = tmp_path / "mcp_apps"
    app_dir = apps_root / "readonly"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(json.dumps({"permissions": ["grove_read"]}))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    m = _register()
    out = _call_dict(m, "grove_heartbeat", {"app_id": "readonly"})
    assert "error" in out
    assert "gate denied" in out["error"]


@pytest.mark.parametrize("read_only_seat,permissions", [
    ("skirnir", ["dispatch_read", "context", "grove_read"]),
    ("vishwakarma", ["dispatch_read", "store_read", "knowledge_read", "grove_read"]),
])
def test_gate_denies_write_and_allows_read_for_grove_read_only_seats(
    tmp_path, monkeypatch, read_only_seat, permissions
):
    """(c) skirnir (witness) and vishwakarma (architect) are ratified
    grove_read-only per docs/design/permissions-matrix.md — the gate must
    deny a write tool and allow a read tool for both."""
    apps_root = tmp_path / "mcp_apps"
    app_dir = apps_root / read_only_seat
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(json.dumps({"permissions": permissions}))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    m = _register()

    out = _call_dict(m, "grove_send_message", {
        "channel_name": "general", "content": "hi", "app_id": read_only_seat,
    })
    assert "error" in out
    assert "gate denied" in out["error"]

    pg = _FakePg([(["id", "name", "channel_type", "description", "created_at",
                     "updated_at", "is_archived", "agent_name"], [], 0),
                  (None, [], 0)])
    monkeypatch.setattr(grove_tools, "get_pg", lambda: pg)
    hist = _call_list(m, "grove_get_history", {"channel_name": "general", "app_id": read_only_seat})
    assert hist == []  # empty result, not a gate-denied error


def test_gate_denies_with_no_app_id_at_all():
    m = _register()
    out = _call_list(m, "grove_list_channels", {})
    assert "error" in out[0]
    assert "gate denied" in out[0]["error"]


def test_gate_allows_read_tool_with_grove_read_group(monkeypatch):
    m = _register()
    pg = _FakePg([(["id", "name", "channel_type", "description", "created_at",
                     "updated_at", "is_archived", "agent_name"], [], 0)])
    monkeypatch.setattr(grove_tools, "get_pg", lambda: pg)
    out = _call_list(m, "grove_list_channels", {"app_id": _APP})
    assert out == []  # no error, just empty — gate let the call through


def test_gate_allows_write_tool_with_grove_write_group(monkeypatch):
    m = _register()
    list_cols = ["id", "name", "channel_type", "description", "created_at",
                 "updated_at", "is_archived", "agent_name"]
    msg_cols = ["id", "channel_id", "sender", "content", "to_agent", "bus_type",
                "priority", "correlation_id", "ttl", "created_at"]
    pg = _FakePg([
        (list_cols, [(1, "general", "group", None, _now(), _now(), False, None)], 0),
        (msg_cols, [(1, 1, _APP, f"{_APP} online", "__all__", "HEARTBEAT", 6, None, None, _now())], 0),
    ])
    monkeypatch.setattr(grove_tools, "get_pg", lambda: pg)
    out = _call_dict(m, "grove_heartbeat", {"app_id": _APP})
    assert out["sender"] == _APP  # no registry row -> resolved sender is app_id
    assert out["bus_type"] == "HEARTBEAT"


# ── reads return rows with datetimes serialized ─────────────────────────────

def test_grove_list_channels_returns_row_fields(monkeypatch):
    m = _register()
    cols = ["id", "name", "channel_type", "description", "created_at",
            "updated_at", "is_archived", "agent_name"]
    rows = [(1, "general", "group", "General chat", _now(), _now(), False, None)]
    pg = _FakePg([(cols, rows, 0)])
    monkeypatch.setattr(grove_tools, "get_pg", lambda: pg)
    out = _call_list(m, "grove_list_channels", {"app_id": _APP})
    assert out == [{"id": 1, "name": "general", "type": "group", "description": "General chat"}]


def test_grove_get_history_serializes_created_at_to_iso_string(monkeypatch):
    m = _register()
    list_cols = ["id", "name", "channel_type", "description", "created_at",
                 "updated_at", "is_archived", "agent_name"]
    msg_cols = grove._MSG_COLUMNS.split(", ")
    msg_row = (5, 1, "hanuman", "hi fleet", "text", None, "__all__", "EVENT", 3,
               None, None, None, _now(), 0)
    pg = _FakePg([
        (list_cols, [(1, "general", "group", None, _now(), _now(), False, None)], 0),
        (msg_cols, [msg_row], 0),
    ])
    monkeypatch.setattr(grove_tools, "get_pg", lambda: pg)
    out = _call_list(m, "grove_get_history", {"channel_name": "general", "app_id": _APP, "since_id": 4})
    assert out[0]["id"] == 5
    assert out[0]["created_at"] == _now().isoformat()
    assert isinstance(out[0]["created_at"], str)


def test_grove_agents_serializes_datetime(monkeypatch):
    m = _register()
    pg = _FakePg([(None, [("hanuman", _now())], 0)])
    monkeypatch.setattr(grove_tools, "get_pg", lambda: pg)
    out = _call_list(m, "grove_agents", {"app_id": _APP})
    assert out[0]["sender"] == "hanuman"
    assert out[0]["last_seen_at"] == _now().isoformat()
    assert isinstance(out[0]["age_secs"], int)


# ── postgres unavailable ────────────────────────────────────────────────────

def test_grove_list_channels_reports_postgres_unavailable(monkeypatch):
    m = _register()
    monkeypatch.setattr(grove_tools, "get_pg", lambda: None)
    out = _call_list(m, "grove_list_channels", {"app_id": _APP})
    assert out[0]["error"] == "postgres_unavailable"


def test_grove_send_message_reports_grove_unavailable_on_missing_schema(monkeypatch):
    import psycopg2.errors

    class _BrokenCursor(_FakeCursor):
        def execute(self, sql, params=None):
            raise psycopg2.errors.UndefinedTable('relation "grove.channels" does not exist')

    class _BrokenPg(_FakePg):
        def cursor(self):
            return _BrokenCursor(self)

    m = _register()
    monkeypatch.setattr(grove_tools, "get_pg", lambda: _BrokenPg([]))
    out = _call_dict(m, "grove_send_message", {"channel_name": "general", "content": "hi", "app_id": _APP})
    assert out["error"] == "grove_unavailable"
    assert "WILLOW_PG_DB=willow_20" in out["detail"]


# ── sender resolution: registry grove_sender, never "Auto" ─────────────────

def test_resolve_grove_sender_uses_registry_row_for_known_agent():
    # "hanuman" is a real seed specialist (bundle/config/specialists.json)
    # with grove_sender="hanuman" — exercised without any home overlay.
    assert grove_tools.resolve_grove_sender("hanuman") == "hanuman"


def test_resolve_grove_sender_falls_back_to_app_id_for_unknown_agent():
    assert grove_tools.resolve_grove_sender("some-unregistered-app") == "some-unregistered-app"


def test_grove_send_message_uses_resolved_sender_not_literal_auto(monkeypatch):
    m = _register()
    list_cols = ["id", "name", "channel_type", "description", "created_at",
                 "updated_at", "is_archived", "agent_name"]
    msg_cols = grove._MSG_COLUMNS.split(", ")
    pg = _FakePg([
        (list_cols, [(1, "general", "group", None, _now(), _now(), False, None)], 0),
        (msg_cols, [(9, 1, "hanuman", "hi", "text", None, "__all__", "EVENT", 3, None, None, None, _now(), 0)], 0),
    ])
    monkeypatch.setattr(grove_tools, "get_pg", lambda: pg)
    # app_id "grovetest" has no registry row, so resolve_grove_sender falls
    # back to the app_id itself — the point being it is NEVER "Auto".
    out = _call_dict(m, "grove_send_message", {"channel_name": "general", "content": "hi", "app_id": _APP})
    assert out["sent"] is True
    # the INSERT's sender param (2nd positional) must be the resolved
    # identity, not the literal string "Auto" the canonical tool defaulted to.
    insert_call = [c for c in pg.calls if c[0] and "INSERT INTO grove.messages" in c[0]][0]
    _sql, params = insert_call
    assert params[1] == _APP  # resolved sender (no registry row -> app_id)
    assert params[1] != "Auto"


def test_grove_send_message_rejects_mismatched_sender_without_grove_relay(monkeypatch):
    """FIX 1 (sender lock): without the grove_relay capability, an explicit
    sender that does not match the caller's own resolved identity is
    REJECTED with sender_forbidden — no DB write happens at all."""
    m = _register()
    pg = _FakePg([])
    monkeypatch.setattr(grove_tools, "get_pg", lambda: pg)
    out = _call_dict(m, "grove_send_message", {
        "channel_name": "general", "content": "hi", "app_id": _APP,
        "sender": "orchestrator-relay",
    })
    assert out["error"] == "sender_forbidden"
    assert "grove_relay" in out["detail"]
    assert _APP in out["detail"]
    # no channel lookup, no INSERT — rejected before any DB access
    assert pg.calls == []


def test_grove_send_message_honors_explicit_sender_override_with_grove_relay(tmp_path, monkeypatch):
    """With grove_relay granted, the same override succeeds."""
    apps_root = tmp_path / "mcp_apps"
    app_dir = apps_root / "relayapp"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["grove_read", "grove_write", "grove_relay"]})
    )
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    m = _register()
    list_cols = ["id", "name", "channel_type", "description", "created_at",
                 "updated_at", "is_archived", "agent_name"]
    msg_cols = grove._MSG_COLUMNS.split(", ")
    pg = _FakePg([
        (list_cols, [(1, "general", "group", None, _now(), _now(), False, None)], 0),
        (msg_cols, [(9, 1, "orchestrator-relay", "hi", "text", None, "__all__", "EVENT", 3, None, None, None, _now(), 0)], 0),
    ])
    monkeypatch.setattr(grove_tools, "get_pg", lambda: pg)
    out = _call_dict(m, "grove_send_message", {
        "channel_name": "general", "content": "hi", "app_id": "relayapp",
        "sender": "orchestrator-relay",
    })
    assert out["sent"] is True
    insert_call = [c for c in pg.calls if c[0] and "INSERT INTO grove.messages" in c[0]][0]
    _sql, params = insert_call
    assert params[1] == "orchestrator-relay"


def test_grove_write_alone_does_not_confer_relay(monkeypatch):
    """(d) grove_write is not grove_relay — holding one must not silently
    grant the other."""
    from willow_mcp import gate
    assert not gate.grove_relay_permitted(_APP)  # _APP has grove_write, not grove_relay


def test_sender_empty_and_sender_equal_caller_both_resolve_and_write(monkeypatch):
    """(a) An empty sender and a sender equal to the caller's own resolved
    identity both write successfully as the caller — no grove_relay needed
    for either."""
    m = _register()
    list_cols = ["id", "name", "channel_type", "description", "created_at",
                 "updated_at", "is_archived", "agent_name"]
    msg_cols = grove._MSG_COLUMNS.split(", ")

    # empty sender
    pg1 = _FakePg([
        (list_cols, [(1, "general", "group", None, _now(), _now(), False, None)], 0),
        (msg_cols, [(9, 1, _APP, "hi", "text", None, "__all__", "EVENT", 3, None, None, None, _now(), 0)], 0),
    ])
    monkeypatch.setattr(grove_tools, "get_pg", lambda: pg1)
    out1 = _call_dict(m, "grove_send_message", {"channel_name": "general", "content": "hi", "app_id": _APP})
    assert out1["sent"] is True
    insert1 = [c for c in pg1.calls if c[0] and "INSERT INTO grove.messages" in c[0]][0]
    assert insert1[1][1] == _APP

    # sender explicitly equal to the caller's own resolved identity
    pg2 = _FakePg([
        (list_cols, [(1, "general", "group", None, _now(), _now(), False, None)], 0),
        (msg_cols, [(10, 1, _APP, "hi again", "text", None, "__all__", "EVENT", 3, None, None, None, _now(), 0)], 0),
    ])
    monkeypatch.setattr(grove_tools, "get_pg", lambda: pg2)
    out2 = _call_dict(m, "grove_send_message", {
        "channel_name": "general", "content": "hi again", "app_id": _APP, "sender": _APP,
    })
    assert out2["sent"] is True
    insert2 = [c for c in pg2.calls if c[0] and "INSERT INTO grove.messages" in c[0]][0]
    assert insert2[1][1] == _APP


def test_mismatched_sender_rejected_across_multiple_write_tools(monkeypatch):
    """(b) The sender lock applies uniformly — spot-check two more write
    tools beyond grove_send_message."""
    m = _register()
    pg = _FakePg([])
    monkeypatch.setattr(grove_tools, "get_pg", lambda: pg)

    out_heartbeat = _call_dict(m, "grove_heartbeat", {"app_id": _APP, "sender": "someone-else"})
    assert out_heartbeat["error"] == "sender_forbidden"
    assert pg.calls == []

    out_flag = _call_dict(m, "grove_flag", {
        "message_id": 1, "flag": "starred", "app_id": _APP, "sender": "someone-else",
    })
    assert out_flag["error"] == "sender_forbidden"
    assert pg.calls == []


# ── grove_get_identity ───────────────────────────────────────────────────────

def test_grove_get_identity_returns_app_id_and_resolved_sender():
    m = _register()
    out = _call_dict(m, "grove_get_identity", {"app_id": _APP})
    assert out["app_id"] == _APP
    assert out["grove_sender"] == _APP  # no registry row for this test app_id
    assert "display_name" in out and "role" in out


def test_grove_get_identity_reflects_registry_row_for_a_known_agent(tmp_path, monkeypatch):
    apps_root = tmp_path / "mcp_apps"
    app_dir = apps_root / "hanuman"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(json.dumps({"permissions": ["grove_read"]}))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    m = _register()
    out = _call_dict(m, "grove_get_identity", {"app_id": "hanuman"})
    assert out["app_id"] == "hanuman"
    assert out["grove_sender"] == "hanuman"
    assert out["role"] == "builder"


def test_grove_get_identity_denied_without_grove_read(ungranted_app):
    m = _register()
    out = _call_dict(m, "grove_get_identity", {"app_id": ungranted_app})
    assert "error" in out
    assert "gate denied" in out["error"]
