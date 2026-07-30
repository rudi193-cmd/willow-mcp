# MCP Python SDK 2.0 — what actually broke

Measured, not predicted: `mcp` 2.0.0 installed in a clean venv, suite run, every
failure chased to its cause.

## The headline correction

`docs/design/mcp-2026-07-28-diff.md` said:

> **Our exposure is small, because both servers use `FastMCP`.** … the SDK
> absorbs them. This is an SDK upgrade, not a rewrite.

**That is false.** `FastMCP` does not exist in SDK 2.0 — zero occurrences in the
package, no compatibility shim. It is replaced by `MCPServer` in
`mcp.server.mcpserver`. Using FastMCP was not what made our exposure small; it
was the single largest thing to change.

The prediction was wrong in the reassuring direction, which is the direction that
matters. It was written from a release-candidate blog post rather than an
installed SDK.

## What the migration actually cost

Smaller than the correction above implies, because `MCPServer` kept the surface
we use — `tool`, `custom_route`, `run`, `auth_server_provider`:

| Change | Fix |
|---|---|
| `mcp.server.fastmcp` → `mcp.server.mcpserver`, `FastMCP` → `MCPServer` | mechanical rename, 16 refs |
| `host`/`port` no longer constructor kwargs | moved to `run(transport=…, host=, port=)` — the stateless core making "where this instance listens" a property of the run, not the server |
| `mcp.settings.host/port` gone | there is no second copy to assert against; `test_cli_args` checks the module's resolved values only |
| `call_tool()` returns `CallToolResult`, not `(content_blocks, structured)` | test helper reads `.structured_content`, handling both shapes |

All 103 tools register unchanged. Every other SDK import we use still resolves:
`mcp.shared.auth`, `mcp.server.auth.provider`, `mcp.server.auth.settings`,
`mcp.server.auth.middleware.auth_context`, `mcp.server.transport_security`.

**1497 passed, 43 skipped, 8 xfailed, 0 failures. ruff clean. path-guard OK.**

## What is blocked, and why

**The per-call credential channel.** `mcp.server.lowlevel.server.request_ctx` is
gone. SDK 2.0 has exactly one `ContextVar` left (`auth_context_var`, for OAuth);
the ambient request context is deliberately removed. `Context` — carrying
`.meta`, `.headers`, `.session_id` — is now **injected into tool functions as a
parameter**.

So `_read_call_credential()`, an ambient no-argument function, cannot be
implemented as written. Porting it means threading `Context` through `_guarded`,
which wraps 109 tools. That is a design decision, not a rename, and it is left
undone here deliberately.

**This was predicted, and the prediction was right.** The box review flagged
`_read_call_credential`'s blanket `except` around a private symbol: *"If the SDK
moves or renames either — plausible in a release built around a stateless core —
this returns `None` forever with no signal."* Verified on 2.0:

```
_read_call_credential() -> None
```

Silently. So this change makes the failure **loud**: a narrow `except ImportError`
with a one-time `logger.error`, exactly the fix that review recommended. The
consequences it named are both real:

- **enforcement OFF** (default) — `_observe_binding` records nothing, so an
  operator watching an empty `bind_observed` stream concludes "no client is
  signing yet" rather than "my SDK moved a symbol". The observation phase that
  gates the enforcement decision goes dark without saying so.
- **enforcement ON** (`WILLOW_MCP_ENFORCE_BINDING=1`) — **every registered agent
  is denied.** Fail-closed, but a total lockout.

**Do not enable enforcement on SDK 2.0 until this is ported.**

Two test files are skipped with that reason recorded in the skip message:
`tests/test_signing.py` (17 tests) and `tests/test_signing_e2e.py`, the latter
also blocked by the removal of
`mcp.shared.memory.create_connected_server_and_client_session` — the in-memory
client/server pair is now built from `create_client_server_memory_streams`.

## The upside this unlocks

SEP-2575 makes `_meta` on every request the official carrier for client info and
capabilities. The port is not merely restoring what broke: it moves the
credential channel from a private convention riding a private symbol under a
blanket `except`, to a documented field on an injected object. `Context.headers`
also exposes the now-required `Mcp-Method` / `Mcp-Name` routing headers.

## Not addressed here

- **`application_type` at DCR (SEP-837)** — mandatory for clients; 0 hits in this
  repo. Ours is the authorization-server side.
- **RFC 9207 `iss` (SEP-2468)** — servers SHOULD send it, **clients MUST validate
  a present `iss` against the recorded issuer.** This collides with the shadowed
  key already recorded in the box review: `oauth.py` stores
  `"issuer": "google"|"apple"` — the upstream IdP name — where RFC 9207 means
  *this* authorization server's issuer URL. Rename the internal field to `idp`
  before implementing 9207, or `resolve_app_id` finds no binding for anyone.
- **Tasks extension (SEP-2663)**, `ttlMs`/`cacheScope` (SEP-2549) — 0 hits;
  nothing to migrate, only something to adopt.
- **Grove** (`safe-app-willow-grove`) is pinned `mcp>=1.28.1,<2.0.0` and unported.
  It uses FastMCP too, so it faces the same rename plus its own
  `_transport_security()` work.
