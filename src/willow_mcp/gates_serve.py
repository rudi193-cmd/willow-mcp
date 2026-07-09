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

from . import gates_actions, gates_panel

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>willow-mcp gates (live)</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --bg: #0b0d12; --card: #161a22; --border: #262c38; --text: #e6e9ef; --muted: #8b93a3;
    --on: #1f9d55; --on-glow: #22c55e; --off: #c0392b; --off-glow: #ef4444; --warn: #b8860b;
    --accent: #3b82f6;
  }
  @media (prefers-color-scheme: light) {
    :root { --bg: #f3f4f6; --card: #ffffff; --border: #dde1e8; --text: #14171f; --muted: #5b6472; }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 2rem 1.25rem 4rem; background: var(--bg); color: var(--text);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  h1 { font-size: 1.3rem; margin: 0 0 .25rem; }
  .sub { color: var(--muted); margin: 0 0 1.75rem; font-size: .9rem; }
  .scope-heading {
    margin: 2rem 0 .75rem; font-size: .78rem; letter-spacing: .06em; text-transform: uppercase;
    color: var(--muted); border-bottom: 1px solid var(--border); padding-bottom: .4rem;
  }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: .9rem; }
  .card {
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 1rem; display: flex; flex-direction: column; gap: .55rem; min-width: 0;
  }
  .card-head { display: flex; align-items: center; gap: .6rem; min-width: 0; }
  .card-head-text { min-width: 0; }
  .label { font-weight: 600; overflow-wrap: anywhere; }
  .tech { font-size: .72rem; color: var(--muted); font-family: ui-monospace, monospace; overflow-wrap: anywhere; }
  .btn {
    appearance: none; border: none; border-radius: 999px; padding: .3rem .85rem;
    font-weight: 700; font-size: .72rem; letter-spacing: .05em; color: #fff; cursor: default;
    flex-shrink: 0;
  }
  .btn.on  { background: var(--on);  box-shadow: 0 0 0 3px color-mix(in srgb, var(--on-glow) 30%, transparent); }
  .btn.off { background: var(--off); box-shadow: 0 0 0 3px color-mix(in srgb, var(--off-glow) 30%, transparent); }
  .btn.warn{ background: var(--warn); }
  .btn.actionable { cursor: pointer; }
  .btn.actionable:hover { filter: brightness(1.15); transform: scale(1.03); }
  .timer { font-variant-numeric: tabular-nums; font-size: .85rem; color: var(--muted); }
  .detail { font-size: .82rem; color: var(--muted); overflow-wrap: anywhere; }
  .note { font-size: .78rem; color: var(--muted); font-style: italic; margin-top: auto; }
  .status { font-size: .78rem; margin-top: auto; min-height: 1.1rem; }
  .status.ok { color: var(--on-glow); }
  .status.err { color: var(--off-glow); }
  .topbar { display: flex; align-items: center; gap: .75rem; margin-bottom: .25rem; }
  .live-dot {
    width: 8px; height: 8px; border-radius: 50%; background: var(--accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 30%, transparent);
    animation: pulse 2s ease-in-out infinite;
  }
  @keyframes pulse { 0%, 100% { opacity: .5; } 50% { opacity: 1; } }
  @media (prefers-reduced-motion: reduce) { .live-dot { animation: none; } }
</style>
</head>
<body>
<div class="topbar"><span class="live-dot"></span><h1>willow-mcp gates — live</h1></div>
<p class="sub">Buttons here call the real action — grant/revoke a lease, allow/deny a permission,
confirm a binding, drain the queue once. Refreshes automatically after every action.
127.0.0.1-only by default; this is a mutation-capable local admin surface, never an MCP tool.</p>
<div id="root"></div>
<script>
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

function fmtRemaining(s) {
  if (s === null || s <= 0) return "no active grant";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h > 0 ? `expires in ${h}h${mm}m${ss}s` : `expires in ${m}m${ss}s`;
}

function timerText(row) {
  if (row.timer_shape === "lease") return fmtRemaining(row.remaining_seconds);
  if (row.timer_shape === "standing") return "standing — no expiry";
  if (row.timer_shape === "process") return "process-lifetime — restart to change";
  return "—";
}

async function describeAction(rowId) {
  const res = await fetch(withAppId("/api/describe", "row_id=" + encodeURIComponent(rowId)));
  return res.json();
}

async function fireAction(row, statusEl) {
  const spec = await describeAction(row.id);
  if (spec.kind === "none") {
    statusEl.textContent = spec.reason || "no live action for this gate";
    statusEl.className = "status";
    return;
  }
  const inputs = {};
  for (const field of spec.needs || []) {
    const value = window.prompt(`${field}:`, field === "ttl" ? "30m" : "");
    if (value === null) { statusEl.textContent = "cancelled"; statusEl.className = "status"; return; }
    inputs[field] = value;
  }
  statusEl.textContent = "working…";
  statusEl.className = "status";
  const res = await fetch(withAppId("/api/action"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({row_id: row.id, inputs}),
  });
  const result = await res.json();
  statusEl.textContent = result.message;
  statusEl.className = "status " + (result.ok ? "ok" : "err");
  await renderFromServer();
}

async function renderFromServer() {
  const rows = await fetchState();
  const root = document.getElementById("root");
  root.innerHTML = "";
  const scopes = [...new Set(rows.map(r => r.scope))];
  for (const scope of scopes) {
    const heading = document.createElement("div");
    heading.className = "scope-heading";
    heading.textContent = scope;
    root.appendChild(heading);
    const grid = document.createElement("div");
    grid.className = "grid";
    for (const row of rows.filter(r => r.scope === scope)) {
      const card = document.createElement("div");
      card.className = "card";
      const head = document.createElement("div");
      head.className = "card-head";
      const btn = document.createElement("button");
      const actionable = !!(row.action_cli) || row.id.startsWith("perm.") ||
                          (row.id.startsWith("lease.")) ||
                          (row.id.startsWith("binding.") && row.state === "off") ||
                          (row.id === "worker" && row.state !== "on");
      btn.className = "btn " + row.state + (actionable ? " actionable" : "");
      btn.textContent = row.state.toUpperCase();
      btn.disabled = !actionable;
      const textWrap = document.createElement("div");
      textWrap.className = "card-head-text";
      const label = document.createElement("div");
      label.className = "label";
      label.textContent = row.friendly;
      const tech = document.createElement("div");
      tech.className = "tech";
      tech.textContent = row.label;
      textWrap.appendChild(label); textWrap.appendChild(tech);
      head.appendChild(btn); head.appendChild(textWrap);
      card.appendChild(head);
      const timer = document.createElement("div");
      timer.className = "timer";
      timer.textContent = timerText(row);
      card.appendChild(timer);
      const detail = document.createElement("div");
      detail.className = "detail";
      detail.textContent = row.detail;
      card.appendChild(detail);
      const status = document.createElement("div");
      status.className = "status";
      if (actionable) {
        btn.onclick = () => fireAction(row, status);
      } else if (row.action_note) {
        const note = document.createElement("div");
        note.className = "note";
        note.textContent = row.action_note;
        card.appendChild(note);
      }
      card.appendChild(status);
      grid.appendChild(card);
    }
    root.appendChild(grid);
  }
}

renderFromServer();
setInterval(renderFromServer, 5000);
</script>
</body>
</html>
"""


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
    page = _PAGE.replace("__WILLOW_GATES_DEFAULT_APP_ID__", json.dumps(default_app_id))
    return HTMLResponse(page)


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
