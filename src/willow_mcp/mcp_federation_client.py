"""The federated MCP client: outbound stdio sessions to ratified downstream
servers.

Complements `signing.py` rather than duplicating it — that module is the
harness a caller of *this* server embeds; this module is what *this server*
embeds to call others. The only other `ClientSession` construction anywhere
in `src/` before this file was `SigningClientSession`, which wraps a session
it does not itself own. This module owns the session.

One `_ServerConnection` per ratified `server_id`: its own asyncio event loop
on its own daemon thread, so one downstream server's slow or hung tool call
can never stall another server's connection or the rest of this (synchronous)
process — the same isolation a per-app egress lease gives identities, applied
here to downstream processes. `list_tools()` is cached eagerly at connect
time (capability aggregation: this is how an orchestrator would answer "what
can I reach across the fleet" without a round trip per server), and both the
cached listing and every call result are run through `external_guard` before
they reach a caller — Decision 4(c): a downstream server's tool names and
descriptions are untrusted input that arrives *before* any output does, so
listings are scanned at listing time, not only results at call time.

Every public function here takes `server_id` and re-derives the connection
from the ratified registry rather than trusting a value cached at connect
time — mirrors `web_fetch.validate_hop` re-validating every redirect instead
of the first resolution (Decision 5).
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from concurrent import futures
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import external_guard, mcp_federation

logger = logging.getLogger("willow_mcp.mcp_federation_client")

#: How long a single stdio round trip (connect, list_tools, or one call_tool)
#: may take before this side gives up on it. A hung child must not hang the
#: calling tool forever.
CALL_TIMEOUT_SECONDS = 30.0
#: How long to wait for a freshly-started thread to publish its event loop.
_LOOP_START_TIMEOUT_SECONDS = 5.0


class FederationClientError(Exception):
    """A connect/call failure that is this module's to report, distinct from
    a gate denial (which is a dict, not an exception — see server.py's
    _guarded convention) and from an MCP protocol error (which the SDK itself
    raises and this module lets propagate)."""


def _scan_text(text: str) -> tuple[str, list[dict]]:
    hits = external_guard.scan(text or "")
    return external_guard.verdict(hits), hits


def _guard_tool_listing(tools: list[Any]) -> list[dict]:
    """Scan every tool's name + description before it ever reaches a caller's
    context — Decision 4(c). A BLOCKED listing entry keeps its `name` (a
    caller must still be able to name what it is refusing) but its
    description is replaced by the sandwich wrap around the flagged text,
    never spliced in verbatim."""
    guarded: list[dict] = []
    for t in tools:
        name = getattr(t, "name", "")
        description = getattr(t, "description", "") or ""
        verdict, hits = _scan_text(f"{name} {description}")
        entry = {
            "name": name,
            "description": description,
            "input_schema": getattr(t, "inputSchema", None),
            "guard_verdict": verdict,
            "guard_hits": hits,
        }
        if verdict == "BLOCKED":
            entry["description"] = external_guard.SANDWICH_TEMPLATE.format(content=description)
        guarded.append(entry)
    return guarded


class _ServerConnection:
    """One downstream server's live stdio session, isolated on its own loop
    and thread. Not constructed directly by callers — see `_get_connection`.
    """

    def __init__(self, server_id: str, entry: dict[str, Any]):
        self.server_id = server_id
        self.entry = entry
        self._thread: Optional[threading.Thread] = None
        self._tools_cache: list[dict] = []
        self.connected_at: Optional[float] = None
        # Thread-safe handoff between the calling (sync) thread and this
        # connection's dedicated asyncio task. `_requests` carries
        # (kind, payload, reply_future) tuples; `concurrent.futures.Future`
        # (NOT asyncio.Future) is the reply channel because it is the one
        # future type safe to touch from both sides of the thread boundary.
        self._requests: "queue.Queue[tuple[str, Any, futures.Future]]" = queue.Queue()
        self._ready = threading.Event()
        self._ready_error: Optional[BaseException] = None

    # -- lifecycle: ONE task owns connect, every call, and disconnect ----
    #
    # anyio's cancel scopes (which stdio_client / ClientSession use
    # internally) are tied to the asyncio Task that entered them — exiting
    # from a *different* task raises "Attempted to exit cancel scope in a
    # different task than it was entered in". Submitting `_connect_async`
    # and `_disconnect_async` as two separate `run_coroutine_threadsafe`
    # calls (even to the same loop) creates two different Tasks and hits
    # exactly that. So: one coroutine, one Task, running for the whole
    # connection's life, fed a queue of requests and replying through
    # thread-safe futures — the standard shape for owning an anyio resource
    # from a background thread.
    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as e:  # pragma: no cover - asyncio.run's own failure
            self._ready_error = e
            self._ready.set()

    async def _main(self) -> None:
        loop = asyncio.get_running_loop()
        spec = mcp_federation.McpServerSpec.from_dict(self.entry)
        if spec.transport != "stdio":
            self._ready_error = FederationClientError(
                f"server {self.server_id!r}: transport {spec.transport!r} not "
                "supported by this client (stdio only)")
            self._ready.set()
            return
        params = StdioServerParameters(
            command=spec.command, args=list(spec.args),
            env=mcp_federation.load_server_env(self.entry), cwd=spec.cwd,
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    self._tools_cache = _guard_tool_listing(listing.tools)
                    self._ready.set()
                    await self._serve_requests(loop, session)
        except Exception as e:
            if not self._ready.is_set():
                self._ready_error = e
                self._ready.set()
            else:
                logger.warning("mcp_federation_client: %s: session ended with "
                               "an error", self.server_id, exc_info=True)

    async def _serve_requests(self, loop: asyncio.AbstractEventLoop, session: ClientSession) -> None:
        """Drain `_requests` until a `shutdown` arrives. The blocking
        `Queue.get` runs in the default executor so it never blocks this
        task's own event loop — the stdio transport's background read task
        shares that loop and must keep running while we wait."""
        while True:
            kind, payload, reply = await loop.run_in_executor(None, self._requests.get)
            if kind == "shutdown":
                reply.set_result(None)
                return
            try:
                if kind == "call":
                    tool, arguments = payload
                    reply.set_result(await session.call_tool(tool, arguments))
                elif kind == "list_tools":
                    listing = await session.list_tools()
                    self._tools_cache = _guard_tool_listing(listing.tools)
                    reply.set_result(self._tools_cache)
                else:  # pragma: no cover - internal misuse only
                    reply.set_exception(FederationClientError(f"unknown request {kind!r}"))
            except Exception as e:
                reply.set_exception(e)

    def _ensure_started(self) -> None:
        if self._thread is not None:
            if self._ready_error is not None:
                raise self._ready_error
            return
        self._thread = threading.Thread(
            target=self._run, name=f"mcp-fed-{self.server_id}", daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=_LOOP_START_TIMEOUT_SECONDS):
            raise FederationClientError(
                f"server {self.server_id!r}: did not become ready in "
                f"{_LOOP_START_TIMEOUT_SECONDS}s")
        if self._ready_error is not None:
            raise self._ready_error
        self.connected_at = time.time()

    def _request(self, kind: str, payload: Any, timeout: float = CALL_TIMEOUT_SECONDS) -> Any:
        self._ensure_started()
        reply: futures.Future = futures.Future()
        self._requests.put((kind, payload, reply))
        return reply.result(timeout=timeout)

    # -- sync-facing API --------------------------------------------------
    def connect(self) -> list[dict]:
        self._ensure_started()
        return self._tools_cache

    def list_tools(self, *, refresh: bool = False) -> list[dict]:
        if refresh:
            return self._request("list_tools", None)
        self._ensure_started()
        return self._tools_cache

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> dict:
        result = self._request("call", (tool, arguments))
        text = "".join(
            getattr(block, "text", "") or "" for block in (result.content or [])
        )
        verdict, hits = _scan_text(text)
        content_text = text
        if verdict == "BLOCKED":
            content_text = external_guard.SANDWICH_TEMPLATE.format(content=text)
        return {
            "is_error": bool(getattr(result, "isError", False)),
            "content_text": content_text,
            "guard_verdict": verdict,
            "guard_hits": hits,
        }

    def disconnect(self) -> None:
        if self._thread is None:
            return
        try:
            self._request("shutdown", None, timeout=CALL_TIMEOUT_SECONDS)
        except Exception:
            logger.warning("mcp_federation_client: %s: shutdown request failed",
                           self.server_id, exc_info=True)
        self._thread.join(timeout=CALL_TIMEOUT_SECONDS)
        self._thread = None
        self._ready = threading.Event()
        self._ready_error = None


_connections: dict[str, _ServerConnection] = {}
_registry_lock = threading.Lock()


def _get_connection(server_id: str) -> _ServerConnection:
    """Resolve (or start) this server's connection. Re-reads the ratified
    registry every time rather than trusting a value cached at first connect
    — a server ratified once and later revoked must not keep answering calls
    through a stale in-memory entry (Decision 5)."""
    entry = mcp_federation.get_ratified(server_id)
    if entry is None:
        raise FederationClientError(
            f"server {server_id!r} is not (or is no longer) in the ratified "
            "registry — a live connection does not outlive ratification")
    with _registry_lock:
        conn = _connections.get(server_id)
        if conn is None:
            conn = _ServerConnection(server_id, entry)
            _connections[server_id] = conn
        else:
            conn.entry = entry
        return conn


def connect_server(server_id: str) -> list[dict]:
    """Connect (or reuse an existing connection) and return the guarded tool
    listing."""
    return _get_connection(server_id).connect()


def list_server_tools(server_id: str, *, refresh: bool = False) -> list[dict]:
    """The cached (or freshly connected) guarded tool listing for one
    server."""
    return _get_connection(server_id).list_tools(refresh=refresh)


def call_tool(server_id: str, tool: str, arguments: Optional[dict[str, Any]] = None) -> dict:
    """Call one tool on one connected-or-connecting server. Callers are
    expected to have already cleared `federation_egress.egress_denial` —
    this module has no gate of its own, exactly as `mcp_generic.py`'s
    upstream ancestor did not: connection-layer code is not where
    authorization decisions belong."""
    return _get_connection(server_id).call_tool(tool, dict(arguments or {}))


def disconnect_server(server_id: str) -> bool:
    with _registry_lock:
        conn = _connections.pop(server_id, None)
    if conn is None:
        return False
    conn.disconnect()
    return True


def shutdown_all() -> None:
    """Disconnect every live connection — process teardown / test cleanup."""
    with _registry_lock:
        conns = list(_connections.values())
        _connections.clear()
    for conn in conns:
        conn.disconnect()
