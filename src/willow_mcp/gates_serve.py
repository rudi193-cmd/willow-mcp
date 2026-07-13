"""willow_mcp/gates_serve.py — the live local HTML dashboard for
`willow-mcp gates --serve`.

`gates_panel.render_html()` writes a static snapshot: real state, but a
dead file — clicking a button copies the CLI command to your clipboard
instead of running it. This module is the version with working buttons: a
tiny local-only web server (Starlette + uvicorn, both already hard
dependencies) that serves the same look, but a click actually calls
`gates_actions.apply()` and re-renders the real result.

**This is a mutation-capable local admin surface**, unlike everything else
`gates_panel.py` renders. It is deliberately NOT an MCP tool — reachable
only by running `willow-mcp gates --serve` yourself, on the host that owns
`$WILLOW_HOME`, the same operator-only boundary as `grant-net` and
`confirm-binding`. Binds to `127.0.0.1` by default; overriding `--host`
is possible (matching `--serve`'s own flag) but widens who can flip your
gates, so it prints a loud warning rather than doing it quietly.

Nothing here adds new authority: every POST just calls into
`gates_actions.apply()`, the exact same function the interactive TUI calls.
"""
from __future__ import annotations

import json

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from . import gates_actions, gates_html, gates_panel

_TOP_EXTRA = '<div class="topbar"><span class="live-dot"></span></div>'

_BODY_SCRIPTS = """
const APP_ID = __WILLOW_GATES_DEFAULT_APP_ID__;
const appIdQS = APP_ID ? ("app_id=" + encodeURIComponent(APP_ID)) : "";
function withAppId(path, extra) {
  const qs = [appIdQS, extra].filter(Boolean).join("&");
  return qs ? `${path}?${qs}` : path;
}

async function fetchState() {
  const res = await fetch(withAppId("/api/state"));
  return res.json();
}

async function describeAction(rowId) {
  const res = await fetch(withAppId("/api/describe", "row_id=" + encodeURIComponent(rowId)));
  return res.json();
}

window.onButtonClick = async (row, btn) => {
  const spec = await describeAction(row.id);
  if (spec.kind === "none") {
    showToast(spec.reason || "no live action for this gate", null);
    return;
  }
  const inputs = {};
  for (const field of spec.needs || []) {
    const value = window.prompt(`${field}:`, field === "ttl" ? "30m" : "");
    if (value === null) { showToast("cancelled", null); return; }
    inputs[field] = value;
  }
  btn.disabled = true;
  const res = await fetch(withAppId("/api/action"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({row_id: row.id, inputs}),
  });
  const result = await res.json();
  showToast(result.message, result.ok);
  await refresh();
};

async function refresh() {
  const rows = await fetchState();
  renderDashboard(rows, null);
}

refresh();
setInterval(refresh, 3000);
"""


def _render_page(default_app_id: str) -> str:
    body = _BODY_SCRIPTS.replace(
        "__WILLOW_GATES_DEFAULT_APP_ID__", json.dumps(default_app_id)
    )
    return gates_html.page(
        title="willow-mcp gates — live",
        subtitle="Buttons here call the real action — grant/revoke a lease, allow/deny a "
                 "permission, confirm a binding, drain the queue once. Refreshes automatically "
                 "every few seconds. 127.0.0.1-only by default; this is a mutation-capable "
                 "local admin surface, never an MCP tool.",
        top_extra=_TOP_EXTRA,
        body_scripts=body,
    )


def _app_id_from_request(request: Request) -> str:
    """An explicit `?app_id=` query param wins; otherwise fall back to the
    default this server was started with (`willow-mcp gates <app_id> --serve`),
    so scoping to one app actually takes effect instead of always showing
    every app under mcp_apps/."""
    qp = request.query_params.get("app_id")
    if qp is not None:
        return qp
    return getattr(request.app.state, "default_app_id", "") or ""


async def _index(request: Request) -> HTMLResponse:
    default_app_id = getattr(request.app.state, "default_app_id", "") or ""
    return HTMLResponse(_render_page(default_app_id))


async def _state(request: Request) -> JSONResponse:
    app_id = _app_id_from_request(request)
    rows = gates_panel.collect(app_id)
    return JSONResponse([r.__dict__ for r in rows])


async def _describe(request: Request) -> JSONResponse:
    row_id = request.query_params.get("row_id", "")
    app_id = _app_id_from_request(request)
    row = _find_row(app_id, row_id)
    if row is None:
        return JSONResponse({"kind": "none", "reason": "unknown row"}, status_code=404)
    spec = gates_actions.describe(row)
    return JSONResponse({"kind": spec.kind, "needs": list(spec.needs), "reason": spec.reason})


async def _action(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "message": "malformed request body"}, status_code=400)
    row_id = payload.get("row_id", "")
    inputs = payload.get("inputs") or {}
    app_id = _app_id_from_request(request)
    row = _find_row(app_id, row_id)
    if row is None:
        return JSONResponse({"ok": False, "message": f"unknown row: {row_id!r}"}, status_code=404)
    result = gates_actions.apply(row, inputs)
    return JSONResponse(result)


def _find_row(app_id: str, row_id: str):
    for row in gates_panel.collect(app_id):
        if row.id == row_id:
            return row
    return None


def build_app(default_app_id: str = "") -> Starlette:
    app = Starlette(routes=[
        Route("/", _index),
        Route("/api/state", _state),
        Route("/api/describe", _describe),
        Route("/api/action", _action, methods=["POST"]),
    ])
    app.state.default_app_id = default_app_id
    return app


def run(host: str = "127.0.0.1", port: int = 8788, app_id: str = "") -> None:
    """Serve the live gates dashboard until interrupted (Ctrl-C). `app_id`
    scopes the default view (still overridable per-request via `?app_id=`);
    empty shows every app under mcp_apps/, same default as the CLI/TUI."""
    import uvicorn

    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"WARNING: binding gates --serve to {host!r}, not localhost — "
              "this is a mutation-capable admin surface (grants leases, flips "
              "permissions) with no authentication of its own.")
    print(f"willow-mcp gates --serve on http://{host}:{port} — Ctrl-C to stop")
    uvicorn.run(build_app(app_id), host=host, port=port, log_level="warning")
