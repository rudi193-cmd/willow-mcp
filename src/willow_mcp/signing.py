"""Client-side signing shim for willow-gate binding (H1 "practical shape").

The agent's HARNESS holds the per-agent secret and signs each call — NOT the
model. The model never sees the secret and so cannot fabricate or omit a
signature; an un-instrumented client simply cannot produce the per-call
credential, which is the point (a gated tool is unreachable without the signer).

This module is what a harness embeds. It is pure — it turns `(secret, session)`
into the credential that rides the MCP request's out-of-band `_meta`, and never
imports the server. The server reads the same shape via
`server._read_call_credential()`.

Flow under enforcement (`WILLOW_MCP_ENFORCE_BINDING=1`):

    secret = <installed once by the operator from `willow-mcp register-agent`>
    # 1. check in — the ONE bootstrap call, exempt from the per-call credential
    #    (it authenticates via the header HMAC), so it needs no meta.
    header = build_checkin_header(secret, agent_id, trust_level=3, tools=["read", "write"])
    result = await session.call_tool("session_bind", {"app_id": agent_id, "header": header})
    session_id = result.structuredContent["session_id"]      # (or parse .content)
    signer = ClientSigner(agent_id, secret, session_id)
    # 2. every subsequent call carries a fresh per-call signature in _meta
    await session.call_tool("store_get", {"app_id": agent_id, "id": "x"},
                            meta=signer.meta_for("store_get"))
    # or: await signed_call_tool(session, signer, "store_get", {...})

The credential rides `_meta`, never a tool argument, so tool schemas stay clean
and the model cannot touch it.
"""
from __future__ import annotations

import json
import secrets as _secrets
from typing import Any, Optional

from .session_binder import call_sig, expected_header_sig

#: The key the credential rides under inside the MCP request's `_meta`. The
#: server reads exactly this key; keep the two in lockstep.
CREDENTIAL_META_KEY = "willow_call_credential"


def build_checkin_header(
    secret: bytes,
    agent_id: str,
    trust_level: int,
    *,
    tools,
    agent_name: Optional[str] = None,
    last_gate: str = "",
    pass_count: int = 0,
    fail_count: int = 0,
    drift: float = 0,
    timestamp: int = 0,
    state_hash: str = "",
    nonce: Optional[str] = None,
) -> dict:
    """Build a signed 13-field check-in header for `session_bind(app_id, header)`.

    `tools` is the willow-gate CLASS list the agent declares it will exercise
    (read/write/execute/admin) — the entry half of the check-out reconciliation.
    `trust_level` is the tier being claimed; the server caps it at the agent's
    registered ceiling, so claiming higher than granted is refused, not honored.
    The nonce is single-use across restarts, so a fresh one is generated per call.
    """
    header = {
        "agent_id": agent_id,
        "agent_name": agent_name or agent_id,
        "last_gate": last_gate,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "drift": drift,
        "nonce": nonce or _secrets.token_hex(16),   # 32 hex chars — matches check_in
        "trust_level": trust_level,
        "timestamp": timestamp,
        "tools": list(tools),
        "state_hash": state_hash,
        "reserved": 0,
        "signature": "0" * 64,
    }
    header["signature"] = expected_header_sig(secret, header)
    return header


def build_call_credential(
    secret: bytes, session_id: str, app_id: str, tool: str, *, call_nonce: Optional[str] = None
) -> dict:
    """The per-call credential for one tool call: `{session_id, call_nonce, sig}`.

    `sig` is HMAC(secret, session_id|app_id|tool|call_nonce) — it binds the call to
    this session, this identity, AND this tool, so a captured credential cannot be
    ridden onto another app_id or replayed for another tool (see the H1 spike). The
    nonce is single-use per session, so a fresh one is generated per call.
    """
    nonce = call_nonce or _secrets.token_hex(16)
    return {
        "session_id": session_id,
        "call_nonce": nonce,
        "sig": call_sig(secret, session_id, app_id, tool, nonce),
    }


def call_meta(
    secret: bytes, session_id: str, app_id: str, tool: str, *, call_nonce: Optional[str] = None
) -> dict:
    """The `meta=` dict to hand `ClientSession.call_tool` for one signed call."""
    return {CREDENTIAL_META_KEY: build_call_credential(
        secret, session_id, app_id, tool, call_nonce=call_nonce)}


class ClientSigner:
    """Holds an agent's secret + live session_id and signs each call. Construct it
    from the `session_bind` result; the model never touches it."""

    def __init__(self, agent_id: str, secret: bytes, session_id: str):
        self.agent_id = agent_id
        self.session_id = session_id
        self._secret = secret

    def meta_for(self, tool: str) -> dict:
        """The `meta=` dict for a call to `tool` as this agent in this session."""
        return call_meta(self._secret, self.session_id, self.agent_id, tool)


async def signed_call_tool(session: Any, signer: ClientSigner, name: str,
                           arguments: Optional[dict] = None, **kwargs):
    """Call an MCP tool with the per-call signature attached to `_meta`.

    Thin convenience over `session.call_tool(name, arguments, meta=...)` — the
    `app_id` still travels as a normal argument (add it to `arguments`); only the
    credential rides `_meta`.
    """
    return await session.call_tool(name, arguments, meta=signer.meta_for(name), **kwargs)


class SigningError(Exception):
    """A signing-harness failure — a refused check-in, or a call before bind."""


def _result_dict(result: Any) -> dict:
    """Best-effort extraction of a willow-mcp tool's dict result from a
    `CallToolResult`, duck-typed so this module never imports the MCP types.
    Handles FastMCP's `structuredContent` (unwrapping its `{"result": …}` box)
    and falls back to JSON in the first text content block."""
    sc = getattr(result, "structuredContent", None)
    if isinstance(sc, dict):
        if set(sc) == {"result"} and isinstance(sc["result"], (dict, list)):
            return sc["result"] if isinstance(sc["result"], dict) else {"result": sc["result"]}
        return sc
    for block in (getattr(result, "content", None) or []):
        text = getattr(block, "text", None)
        if text:
            try:
                parsed = json.loads(text)
                return parsed if isinstance(parsed, dict) else {"result": parsed}
            except (ValueError, TypeError):
                pass
    return {}


class SigningClientSession:
    """A real signing harness wrapping an MCP `ClientSession`.

    The harness — not the model — holds the agent's secret. It checks in ONCE
    (`bind`) and then signs EVERY subsequent tool call (`call`), so a model
    driving the session never sees the secret or a signature and cannot reach a
    gated tool un-instrumented. This is the client half of enforcement; the
    operator installs the secret here out-of-band from `willow-mcp register-agent`.

        harness = SigningClientSession(mcp_session, "worker", secret)
        await harness.bind(trust_level=3, tools=["read", "write"])
        await harness.call("store_put", {"collection": "notes", "record": {...}})
        await harness.reconcile(tools=["read", "write"])   # check-out
    """

    def __init__(self, session: Any, agent_id: str, secret: bytes):
        self._session = session
        self.agent_id = agent_id
        self._secret = secret
        self._signer: Optional[ClientSigner] = None
        self.session_id: Optional[str] = None

    async def bind(self, trust_level: int, *, tools, **header_kw) -> dict:
        """Check in (the one bootstrap call — no per-call credential yet, it
        authenticates via the header HMAC) and arm the per-call signer. Returns
        the session dict; raises SigningError if the gate refuses the header."""
        header = build_checkin_header(self._secret, self.agent_id, trust_level,
                                      tools=tools, **header_kw)
        result = await self._session.call_tool(
            "session_bind", {"app_id": self.agent_id, "header": header})
        data = _result_dict(result)
        if "error" in data or "session_id" not in data:
            raise SigningError(f"check-in refused: {data or 'no result'}")
        self.session_id = data["session_id"]
        self._signer = ClientSigner(self.agent_id, self._secret, self.session_id)
        return data

    async def call(self, name: str, arguments: Optional[dict] = None):
        """Call a gated tool as this agent, signing it. `app_id` is filled in
        automatically; the credential rides `_meta`."""
        if self._signer is None:
            raise SigningError("call bind() before making signed calls")
        args = dict(arguments or {})
        args.setdefault("app_id", self.agent_id)
        return await self._session.call_tool(name, args, meta=self._signer.meta_for(name))

    async def reconcile(self, *, tools, pass_count: int = 0, fail_count: int = 0,
                        drift: float = 0, state_hash: str = "") -> Any:
        """Check out: declare the tool CLASSES you exercised and let the server
        diff them against the receipt log. Signed like any other call."""
        exit_declaration = {"tools": list(tools), "pass_count": pass_count,
                            "fail_count": fail_count, "drift": drift, "state_hash": state_hash}
        return await self.call(
            "session_reconcile",
            {"session_id": self.session_id, "exit_declaration": exit_declaration})
