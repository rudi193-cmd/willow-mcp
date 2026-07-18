"""End-to-end: the signing harness drives the REAL willow-mcp server, over an
in-memory MCP transport, under enforcement.

This exercises the whole path a production client would — session_bind → signed
tool calls carrying the credential in `_meta` → check-out — through the actual
FastMCP dispatch (_guarded → _gate → _enforce_binding_gate → the real tool body),
not a direct `_gate` call. It is the proof the review asked for: enforcement
running without the test harness poking the contextvar.
"""
import asyncio
import json

import pytest

from mcp.shared.memory import create_connected_server_and_client_session as connect

from willow_mcp import server, signing, agent_registry as reg, session_binder as sb
from willow_mcp.db import Store
from willow_mcp.receipts import ReceiptLog


@pytest.fixture
def enforced(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "apps"))
    monkeypatch.setenv("WILLOW_MCP_ENFORCE_BINDING", "1")
    monkeypatch.setattr(server, "_store", Store(str(tmp_path / "store")))
    monkeypatch.setattr(server, "_receipt_log", ReceiptLog(str(tmp_path / "r.db")))
    monkeypatch.setattr(server, "_binder", sb.SessionBinder())
    monkeypatch.setattr(server, "_buckets", {})
    server._CALL_CREDENTIAL.set(None)

    def _manifest(app_id, perms=("full_access",), **extra):
        d = tmp_path / "apps" / app_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({"permissions": list(perms), **extra}))
        return app_id

    return _manifest


def _d(result):
    return signing._result_dict(result)


def test_signing_harness_end_to_end_under_enforcement(enforced):
    enforced("worker", ("full_access",))
    secret = bytes.fromhex(reg.register_agent("worker", 3)["secret_hex"])   # Veteran

    async def scenario():
        async with connect(server.mcp) as session:
            await session.initialize()
            harness = signing.SigningClientSession(session, "worker", secret)

            # 1. check in — the bootstrap call, no per-call credential needed
            bound = await harness.bind(trust_level=3, tools=["read", "write"])
            assert bound["tier"] == "Veteran"

            # 2. a SIGNED write passes end to end (real gate, real store)
            put = _d(await harness.call(
                "store_put", {"collection": "notes", "record": {"text": "hi"},
                              "record_id": "n1"}))
            assert "error" not in put

            # 3. an UNSIGNED call (no _meta) is denied by the real gate
            unsigned = _d(await session.call_tool(
                "store_get", {"app_id": "worker", "collection": "notes", "record_id": "n1"}))
            assert "error" in unsigned and "binding required" in unsigned["error"]

            # 4. the same read, SIGNED, succeeds
            got = _d(await harness.call(
                "store_get", {"collection": "notes", "record_id": "n1"}))
            assert "error" not in got

            # 5. check-out reconciles clean (declared read+write, did read+write)
            rec = _d(await harness.reconcile(tools=["read", "write"]))
            return rec

    rec = asyncio.run(scenario())
    assert rec["clean"] is True


def test_tier_ceiling_denies_over_tier_tool_end_to_end(enforced):
    enforced("rook", ("full_access",))
    secret = bytes.fromhex(reg.register_agent("rook", 1)["secret_hex"])     # Rookie, read-only

    async def scenario():
        async with connect(server.mcp) as session:
            await session.initialize()
            harness = signing.SigningClientSession(session, "rook", secret)
            await harness.bind(trust_level=1, tools=["read"])
            # a Rookie signing a write is denied by the tier ceiling, not the sig
            return _d(await harness.call(
                "store_put", {"collection": "notes", "record": {"x": 1}, "record_id": "z"}))

    out = asyncio.run(scenario())
    assert "error" in out and "tier too low" in out["error"]


def test_unregistered_agent_is_manifest_only_end_to_end(enforced):
    # A plain (unregistered) app under enforcement keeps working with no signing —
    # the opt-in-per-agent rule, exercised through the real transport.
    enforced("plain", ("store_read", "store_write"))

    async def scenario():
        async with connect(server.mcp) as session:
            await session.initialize()
            return _d(await session.call_tool(
                "store_put", {"app_id": "plain", "collection": "c",
                              "record": {"x": 1}, "record_id": "r"}))

    out = asyncio.run(scenario())
    assert "error" not in out
