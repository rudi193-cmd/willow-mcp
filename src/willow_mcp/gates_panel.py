"""willow_mcp/gates_panel.py — every authorization gate, in the egress
lease's shape: on/off, plus how long the "on" is good for.

`lease.py` is the one gate in this codebase with a clock on it — a
`willow-mcp net-status` reader sees "active, expires in 1743s" instead of a
bare boolean. Every other gate (manifest permissions, `task_net`,
`integration_net`, `consent.*`, identity bindings, schema-mapping
confirmation, strict trust root, severance, human-orchestrator attestation)
is a standing boolean
scattered across its own file and its own CLI command or hand-edit, and the
only place that reads all of them together is `diagnostic_summary`'s
problem list — built for "why did a call just fail", not "show me
everything, at a glance, before I start."

This module is that second view. `collect()` builds one `GateRow` per gate
by calling the *same* read functions `diagnostic_summary` already calls —
it adds no new state and changes no enforcement. `render_tui()` and
`render_html()` turn that into a terminal table or a static HTML page,
respectively; both give every "on" gate a countdown-shaped timer field, even
the ones that never expire (labelled `standing`) or that only change at
process start (labelled `process`), because a consistent shape is the point
of showing them together.

**Actionability is deliberately uneven.** A row's `action_cli` is either an
existing operator-only local CLI command (`grant-net`, `revoke-net`,
`confirm-binding`, `worker`) or the new `allow-permission`/`deny-permission`
pair this module's sibling `manifest_admin.py` adds for the one gate that
had no operator affordance before. Gates this process cannot honestly
flip — `consent.*` is read-only in willow-mcp by design (see
`consent.py`'s module docstring: a consumer that writes the policy it is
checked against is not a gate), and `strict_trust_root` / severance /
human-orchestrator attestation are environment variables read once at
process start — carry an `action_note` naming the file or env var to edit
instead, rather than a fake button. Nothing here is an MCP tool; like
`net-status` and `diagnostic_summary`, it is run by the operator on the
host that owns `$WILLOW_HOME`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import escape as _esc
from typing import Optional

from . import consent, lease, paths
from .gate import (
    INTEGRATION_NET_PERMISSION,
    NET_PERMISSION,
    PERMISSION_GROUPS,
    _apps_root,
    _load_manifest,
)
from .heartbeat import read_workers
from .human_session import ORCHESTRATOR_APP_ID, human_orchestrator_attested


@dataclass
class GateRow:
    id: str
    #: The real, exact identifier — a permission group name, a manifest
    #: capability, etc. Never change what this holds: gates_actions.py reads
    #: it to know *what to actually toggle* (e.g. which permission string to
    #: pass to manifest_admin.set_permission), and action_cli commands quote
    #: it verbatim. `friendly` below is the display-only translation.
    label: str
    scope: str                       # "global" or an app_id
    state: str                       # "on" | "off" | "warn"
    detail: str
    remaining_seconds: Optional[int] = None
    expires_at: Optional[str] = None
    #: "lease" (has a real deadline) | "standing" (never expires) |
    #: "process" (only changes at process start) | "n/a" (not a grant at all)
    timer_shape: str = "n/a"
    action_cli: Optional[str] = None
    action_note: Optional[str] = None
    #: Plain-language translation of `label`, for someone who doesn't know
    #: what a "manifest permission group" is. Display-only — every renderer
    #: shows this as the heading and `label` as a secondary technical
    #: reference, never the other way around, so `--json`/CLI output stays
    #: exact. Falls back to a humanized version of `label` for anything
    #: `FRIENDLY_LABELS` doesn't yet cover (see `_friendly()`).
    friendly: str = ""

    def __post_init__(self) -> None:
        if not self.friendly:
            self.friendly = _friendly(self.label)


#: Plain-language translation for every permission group / capability name a
#: `perm.*` row can carry (see `gate.PERMISSION_GROUPS` and the two
#: capability flags). Keyed on the exact string so it stays in sync with
#: whatever gate.py actually grants — a name added there without an entry
#: here just falls back to `_humanize()` rather than erroring.
FRIENDLY_LABELS: dict[str, str] = {
    "store_read": "View saved notes",
    "store_write": "Save and edit notes",
    "store_all": "Full access to saved notes",
    "knowledge_read": "Search what it has learned",
    "knowledge_write": "Teach it new things",
    "task_queue": "Run tasks",
    "agent_dispatch": "Assign work to helpers",
    "dispatch_read": "See assigned work",
    "dispatch_write": "Assign and complete work",
    "orchestrator": "Direct the whole team",
    "fleet_read": "See the helper team",
    "context": "Remember short-term notes",
    "audit": "See its own activity log",
    "gap_read": "See open questions",
    "gap_write": "Log and answer open questions",
    "gap_promote": "Make an answer official knowledge",
    "schema_admin": "Configure database field mapping",
    "full_access": "Full access to everything",
    "integration_read": "Check outside-service status",
    "integration_call": "Talk to outside services",
    "task_net": "Request internet access (for tasks)",
    "integration_net": "Request internet access (for outside services)",
    "consent.internet": "Allow internet access, fleet-wide",
    "consent.cloud_llm": "Allow cloud AI access, fleet-wide",
    "consent.lan": "Allow local network access, fleet-wide",
    "strict_trust_root": "Extra-strict security mode",
    "severance": "Kept separate from other Willow installs",
    "human_orchestrator": "Requires a human in charge",
    "task worker": "Task runner",
    "egress lease": "Temporary internet access",
}


def _humanize(name: str) -> str:
    """Fallback for any technical name with no entry in FRIENDLY_LABELS:
    snake_case / dotted -> "Title case words". Not a translation, just
    something less alarming than a raw identifier until one is added above."""
    return name.replace("_", " ").replace(".", " ").strip().capitalize()


def _friendly(label: str) -> str:
    return FRIENDLY_LABELS.get(label, _humanize(label))


def list_app_ids() -> list[str]:
    """Every app with a manifest directory — excludes the two reserved
    non-app subtrees `lease.py`/`identity_binding.py` keep under the same root."""
    root = _apps_root()
    if not root.is_dir():
        return []
    skip = {"_net_leases", "_identity_bindings"}
    return sorted(p.name for p in root.iterdir() if p.is_dir() and p.name not in skip)


def _global_rows() -> list[GateRow]:
    rows: list[GateRow] = []

    c = consent.read_consent()
    disagreeing = set((c.get("disagreement") or {}).get("keys") or [])
    for key in consent.CONSENT_KEYS:
        on = c["consent"].get(key, False)
        detail = f"source={c.get('source')}"
        if key in disagreeing:
            detail += f" — DISAGREES with mirror: {c['disagreement']}"
        rows.append(GateRow(
            id=f"consent.{key}", label=f"consent.{key}", scope="global",
            state="on" if on else "off", detail=detail, timer_shape="standing",
            action_note=(f"read-only in willow-mcp by design — edit "
                         f"{c['canonical_path']} (authored by willow-2.0) "
                         "or use Grove's settings pane"),
        ))

    strict = lease.strict_trust_root()
    rows.append(GateRow(
        id="strict_trust_root", label="strict_trust_root", scope="global",
        state="on" if strict else "off",
        detail="refuses egress when this process can write its own lease/manifest keys",
        timer_shape="process",
        action_note=("set WILLOW_MCP_STRICT_TRUST_ROOT=1 in the server's environment "
                     "and restart — read once at process start"),
    ))

    asserted = paths.severance_asserted()
    rows.append(GateRow(
        id="severance", label="severance", scope="global",
        state="on" if asserted else "off",
        detail=(f"fleet isolation claim — fleet_home={paths.fleet_home()}, "
                f"fleet_pg_db={paths.fleet_pg_db() or None}"
                if asserted else "fleet isolation claim — not asserted, single-trust-domain install"),
        timer_shape="process",
        action_note=("set WILLOW_MCP_FLEET_HOME / WILLOW_MCP_FLEET_PG_DB in the "
                     "server's environment and restart"),
    ))

    attested = human_orchestrator_attested()
    rows.append(GateRow(
        id="human_orchestrator", label="human_orchestrator", scope="global",
        state="on" if attested else "off",
        detail=f"gates dispatch_send/verify_handoff/agent_clear for app_id={ORCHESTRATOR_APP_ID!r}",
        timer_shape="process",
        action_note=("set WILLOW_HUMAN_ORCHESTRATOR=1 in the orchestrator's own MCP "
                     "server env and restart — never on specialist seats"),
    ))

    workers = read_workers()
    alive = workers.get("alive", 0)
    total = len(workers.get("workers", []))
    rows.append(GateRow(
        id="worker", label="task worker", scope="global",
        state="on" if alive else ("warn" if total else "off"),
        detail=(f"{alive} alive / {total} known" +
                ("" if alive else " — nothing will drain task_submit")),
        timer_shape="n/a",
        action_cli=None if alive else "willow-mcp worker --lane fast",
    ))

    return rows


def _app_rows(app_id: str) -> list[GateRow]:
    rows: list[GateRow] = []
    manifest = _load_manifest(app_id)
    perms = set((manifest or {}).get("permissions") or [])

    capability_flags = (NET_PERMISSION, INTEGRATION_NET_PERMISSION)
    for group in sorted(PERMISSION_GROUPS) + list(capability_flags):
        on = group in perms
        detail = ("capability flag — see also this app's egress lease below"
                   if group in capability_flags else "manifest permission group")
        rows.append(GateRow(
            id=f"perm.{app_id}.{group}", label=group, scope=app_id,
            state="on" if on else "off", detail=detail, timer_shape="standing",
            action_cli=f"willow-mcp {'deny' if on else 'allow'}-permission {app_id} {group}",
        ))

    lst = lease.read_lease(app_id)
    status = lst["status"]
    if status == "active":
        rows.append(GateRow(
            id=f"lease.{app_id}", label="egress lease", scope=app_id, state="on",
            detail=f"issuer={lst.get('issuer')} reason={lst.get('reason') or '(none)'}",
            remaining_seconds=lst["remaining_seconds"], expires_at=lst["expires_at"],
            timer_shape="lease", action_cli=f"willow-mcp revoke-net {app_id}",
        ))
    else:
        detail = {
            "none": "no lease on disk", "expired": "expired",
            "malformed": lst.get("error", "malformed"),
            "mismatch": lst.get("error", "app_id mismatch"),
        }.get(status, status)
        rows.append(GateRow(
            id=f"lease.{app_id}", label="egress lease", scope=app_id, state="off",
            detail=detail, timer_shape="lease",
            action_cli=f'willow-mcp grant-net {app_id} --ttl 30m --reason "..."',
        ))

    return rows


def _binding_rows() -> list[GateRow]:
    rows: list[GateRow] = []
    root = paths.identity_bindings_dir()
    if not root.is_dir():
        return rows
    for f in sorted(root.glob("*.json")):
        try:
            record = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue  # a torn or hand-mangled file is not a binding
        confirmed = bool(record.get("confirmed"))
        detail = f"subject={record.get('subject_id')} email={record.get('email')}"
        if record.get("email_drift"):
            detail += " — EMAIL DRIFT, verify before trusting"
        issuer = record.get("issuer")
        rows.append(GateRow(
            id=f"binding.{f.stem}", label=f"identity binding ({issuer})",
            friendly=f"Signed-in account (via {issuer})",
            scope=record.get("app_id") or "(unbound)",
            state="on" if confirmed else "off", detail=detail, timer_shape="standing",
            action_cli=(None if confirmed else
                        f"willow-mcp confirm-binding --issuer {issuer} "
                        f"--subject {record.get('subject_id')} --app-id <app_id>"),
        ))
    return rows


def collect(app_id: str = "") -> list[GateRow]:
    """Every gate row. Pass `app_id` to scope the per-app rows to one app;
    omit it to show every app under `mcp_apps/`."""
    rows = _global_rows() + _binding_rows()
    for a in ([app_id] if app_id else list_app_ids()):
        rows.extend(_app_rows(a))
    return rows


# ── rendering ────────────────────────────────────────────────────────────────

_ANSI = {"on": "\033[97;42m", "off": "\033[97;41m", "warn": "\033[30;43m", "reset": "\033[0m"}


def _button_text(state: str) -> str:
    return {"on": " ON  ", "off": " OFF ", "warn": "WARN "}.get(state, state.upper())


def _timer_text(row: GateRow) -> str:
    if row.timer_shape == "lease":
        if row.remaining_seconds and row.remaining_seconds > 0:
            h, rem = divmod(row.remaining_seconds, 3600)
            m, s = divmod(rem, 60)
            return f"expires in {h}h{m:02d}m{s:02d}s" if h else f"expires in {m}m{s:02d}s"
        return "no active grant"
    if row.timer_shape == "standing":
        return "standing — no expiry"
    if row.timer_shape == "process":
        return "process-lifetime — restart to change"
    return "—"


def render_tui(rows: list[GateRow], color: bool = True) -> str:
    lines = ["willow-mcp gates — every authorization gate, egress-lease shaped\n"]
    scope_w = max((len(r.scope) for r in rows), default=6)
    label_w = max((len(r.friendly) for r in rows), default=6)
    timer_w = max((len(_timer_text(r)) for r in rows), default=6)
    for r in rows:
        button = _button_text(r.state)
        if color:
            button = f"{_ANSI.get(r.state, '')}{button}{_ANSI['reset']}"
        lines.append(
            f"[{button}] {r.scope:<{scope_w}}  {r.friendly:<{label_w}}  "
            f"{_timer_text(r):<{timer_w}}  {r.label} — {r.detail}"
        )
        if r.action_cli:
            lines.append(f"{'':>{9}}-> {r.action_cli}")
        elif r.action_note:
            lines.append(f"{'':>{9}}-> {r.action_note}")
    return "\n".join(lines)


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>willow-mcp gates</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{
    --bg: #0b0d12; --card: #161a22; --border: #262c38; --text: #e6e9ef; --muted: #8b93a3;
    --on: #1f9d55; --on-glow: #22c55e; --off: #c0392b; --off-glow: #ef4444; --warn: #b8860b;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{ --bg: #f3f4f6; --card: #ffffff; --border: #dde1e8; --text: #14171f; --muted: #5b6472; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 2rem 1.25rem 4rem; background: var(--bg); color: var(--text);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }}
  h1 {{ font-size: 1.3rem; margin: 0 0 .25rem; }}
  .sub {{ color: var(--muted); margin: 0 0 1.75rem; font-size: .9rem; }}
  .scope-heading {{
    margin: 2rem 0 .75rem; font-size: .78rem; letter-spacing: .06em; text-transform: uppercase;
    color: var(--muted); border-bottom: 1px solid var(--border); padding-bottom: .4rem;
  }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: .9rem; }}
  .card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 1rem; display: flex; flex-direction: column; gap: .55rem; min-width: 0;
  }}
  .card-head {{ display: flex; align-items: center; gap: .6rem; min-width: 0; }}
  .card-head-text {{ min-width: 0; }}
  .label {{ font-weight: 600; overflow-wrap: anywhere; }}
  .tech {{ font-size: .72rem; color: var(--muted); font-family: ui-monospace, monospace; overflow-wrap: anywhere; }}
  .btn {{
    appearance: none; border: none; border-radius: 999px; padding: .3rem .85rem;
    font-weight: 700; font-size: .72rem; letter-spacing: .05em; color: #fff; cursor: default;
    flex-shrink: 0;
  }}
  .btn.on  {{ background: var(--on);  box-shadow: 0 0 0 3px color-mix(in srgb, var(--on-glow) 30%, transparent); }}
  .btn.off {{ background: var(--off); box-shadow: 0 0 0 3px color-mix(in srgb, var(--off-glow) 30%, transparent); }}
  .btn.warn{{ background: var(--warn); }}
  .btn.actionable {{ cursor: pointer; }}
  .btn.actionable:hover {{ filter: brightness(1.12); }}
  .timer {{ font-variant-numeric: tabular-nums; font-size: .85rem; color: var(--muted); }}
  .detail {{ font-size: .82rem; color: var(--muted); overflow-wrap: anywhere; }}
  .action {{ display: flex; gap: .4rem; align-items: center; margin-top: auto; }}
  .action code {{
    flex: 1; min-width: 0; background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; padding: .35rem .5rem; font-size: .74rem; overflow-x: auto;
    white-space: pre; color: var(--text);
  }}
  .copy {{
    border: 1px solid var(--border); background: transparent; color: var(--text);
    border-radius: 6px; padding: .35rem .55rem; font-size: .74rem; cursor: pointer;
  }}
  .copy:hover {{ background: var(--border); }}
  .note {{ font-size: .78rem; color: var(--muted); font-style: italic; }}
</style>
</head>
<body>
<h1>willow-mcp gates</h1>
<p class="sub">Every authorization gate, shown the way the egress lease already shows itself —
on/off, plus how long the "on" is good for. Generated once; re-run <code>willow-mcp gates --html</code>
for fresh state. Countdown timers below tick client-side from the moment this file was generated.</p>
<div id="root"></div>
<script>
const ROWS = {rows_json};
const GENERATED_AT = {generated_at_json};

function fmtRemaining(s) {{
  if (s === null || s <= 0) return "no active grant";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h > 0 ? `expires in ${{h}}h${{mm}}m${{ss}}s` : `expires in ${{m}}m${{ss}}s`;
}}

function timerText(row) {{
  if (row.timer_shape === "lease") {{
    if (row.remaining_seconds === null) return "no active grant";
    const elapsed = Math.floor((Date.now() - Date.parse(GENERATED_AT)) / 1000);
    return fmtRemaining(row.remaining_seconds - elapsed);
  }}
  if (row.timer_shape === "standing") return "standing — no expiry";
  if (row.timer_shape === "process") return "process-lifetime — restart to change";
  return "—";
}}

function copy(text, btn) {{
  const done = () => {{ const old = btn.textContent; btn.textContent = "copied"; setTimeout(() => btn.textContent = old, 1200); }};
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  }} else {{
    fallbackCopy(text, done);
  }}
}}
function fallbackCopy(text, done) {{
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  try {{ document.execCommand("copy"); done(); }} catch (e) {{}}
  document.body.removeChild(ta);
}}

function render() {{
  const root = document.getElementById("root");
  root.innerHTML = "";
  const scopes = [...new Set(ROWS.map(r => r.scope))];
  for (const scope of scopes) {{
    const heading = document.createElement("div");
    heading.className = "scope-heading";
    heading.textContent = scope;
    root.appendChild(heading);
    const grid = document.createElement("div");
    grid.className = "grid";
    for (const row of ROWS.filter(r => r.scope === scope)) {{
      const card = document.createElement("div");
      card.className = "card";
      const head = document.createElement("div");
      head.className = "card-head";
      const btn = document.createElement("span");
      btn.className = "btn " + row.state;
      btn.textContent = row.state.toUpperCase();
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
      timer.dataset.row = row.id;
      timer.textContent = timerText(row);
      card.appendChild(timer);
      const detail = document.createElement("div");
      detail.className = "detail";
      detail.textContent = row.detail;
      card.appendChild(detail);
      if (row.action_cli) {{
        const action = document.createElement("div");
        action.className = "action";
        const code = document.createElement("code");
        code.textContent = row.action_cli;
        const copyBtn = document.createElement("button");
        copyBtn.className = "copy";
        copyBtn.textContent = "copy";
        copyBtn.onclick = () => copy(row.action_cli, copyBtn);
        action.appendChild(code); action.appendChild(copyBtn);
        card.appendChild(action);
      }} else if (row.action_note) {{
        const note = document.createElement("div");
        note.className = "note";
        note.textContent = row.action_note;
        card.appendChild(note);
      }}
      grid.appendChild(card);
    }}
    root.appendChild(grid);
  }}
}}

render();
setInterval(() => {{
  document.querySelectorAll(".timer").forEach(el => {{
    const row = ROWS.find(r => r.id === el.dataset.row);
    if (row) el.textContent = timerText(row);
  }});
}}, 1000);
</script>
</body>
</html>
"""


def render_html(rows: list[GateRow], generated_at: str) -> str:
    rows_payload = [
        {
            "id": r.id, "label": r.label, "friendly": r.friendly, "scope": r.scope,
            "state": r.state, "detail": r.detail, "remaining_seconds": r.remaining_seconds,
            "timer_shape": r.timer_shape, "action_cli": r.action_cli,
            "action_note": r.action_note,
        }
        for r in rows
    ]
    # json.dumps output is safe to inline in a <script> block except for the
    # literal substring "</script>", which would close the tag early.
    rows_json = json.dumps(rows_payload).replace("</script>", "<\\/script>")
    return _HTML_TEMPLATE.format(
        rows_json=rows_json,
        generated_at_json=json.dumps(generated_at),
    )
