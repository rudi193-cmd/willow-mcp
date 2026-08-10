"""Stdio MCP server fixture that speaks the willow-gate binding protocol, so
tests/test_mcp_federation_client_signing.py can drive the federated client's
outbound signing over a real subprocess rather than a mock.

Deliberately NOT willow-mcp itself. It implements only what the outbound path
touches, and it verifies the check-in HMAC **for real** rather than trusting
that a header is present — a bind test that accepts any header would pass just
as happily against a client that signed with the wrong key.

  session_bind(app_id, header)      verify the 13-field header signature, mint
                                    a session_id, or refuse
  echo(text)                        an ordinary call to make while bound
  session_reconcile(app_id, ...)    record the check-out declaration
  probe()                           report what this fixture observed

The per-call `_meta` credential is intentionally NOT asserted here: SDK 2.0
removed the ambient request context, and willow-mcp reads `_meta` through
middleware of its own (`request_context.current_meta`). Reimplementing that in a
fixture would be testing the plumbing rather than the client, so the per-call
signature is asserted in the test module where it is directly observable.

The shared secret arrives via $BINDING_FIXTURE_SECRET (hex) — the same
out-of-band install a real deployment does.
"""
import asyncio
import hashlib
import hmac
import json
import os

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("binding-fixture")

SECRET = bytes.fromhex(os.environ.get("BINDING_FIXTURE_SECRET", "") or "00")
SESSION_ID = "fixture-session-0001"

#: Mirrors willow_mcp.signing._SIGNED_FIELDS — the header fields under the HMAC.
_SIGNED_FIELDS = ("agent_id", "agent_name", "last_gate", "pass_count", "fail_count",
                  "drift", "nonce", "trust_level", "timestamp", "tools", "state_hash",
                  "reserved")

observed = {"bind_attempts": 0, "bound_as": None, "declared_tools": None,
            "reconciled": None, "echo_calls": 0}


def _header_sig(secret: bytes, header: dict) -> str:
    canon = json.dumps({k: header[k] for k in _SIGNED_FIELDS},
                       sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret, canon, hashlib.sha256).hexdigest()


@mcp.tool()
def session_bind(app_id: str, header: dict) -> dict:
    observed["bind_attempts"] += 1
    try:
        expected = _header_sig(SECRET, header)
    except KeyError as e:
        return {"error": f"malformed header, missing {e}"}
    if not hmac.compare_digest(str(header.get("signature", "")), expected):
        return {"error": "bad header signature"}
    observed["bound_as"] = app_id
    observed["declared_tools"] = list(header.get("tools") or [])
    return {"session_id": SESSION_ID, "tier": "Veteran",
            "trust_level": header.get("trust_level")}


@mcp.tool()
def echo(text: str = "") -> str:
    observed["echo_calls"] += 1
    return text


@mcp.tool()
def session_reconcile(app_id: str = "", exit_declaration: dict | None = None) -> dict:
    observed["reconciled"] = dict(exit_declaration or {})
    return {"clean": True}


@mcp.tool()
def probe() -> dict:
    """What this fixture saw — asserted by the test after the client acts."""
    return dict(observed)


if __name__ == "__main__":
    asyncio.run(mcp.run_stdio_async())
