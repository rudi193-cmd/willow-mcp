"""Human-only orchestrator seat — trust boundary for app_id=willow.

The orchestrator (Willow) is always run by a human operator, never by a
dispatched agent. Prompt injection in assignment.md or handoff narratives must
not be able to *become* the orchestrator or invoke orchestrator write tools.

Enforcement layers (defense in depth):
  1. session_enter(willow) → human_orchestrator only; never dispatch path
  2. Orchestrator write tools require human host attestation (stdio) or OAuth
     binding to willow (serve mode)
  3. Specialists use their own app_id; willow manifest not wired in worker MCP configs
  4. verify_handoff reads structured handoff.json — narrative is evidence, not instructions

See docs/design/human-orchestrator.md
"""

from __future__ import annotations

import os

ORCHESTRATOR_APP_ID = "willow"

# Tools that advance fleet work on behalf of the operator — never agent-autonomous.
# frank_append and envelope_apply mutate the shared governance chain; a process
# claiming app_id=willow must be a human-attested orchestrator host to run them,
# so a prompt-injected agent forging the willow seat cannot append or cite as the
# orchestrator (Loki B5FB7E2B §4.2). A non-willow app still reaches them only
# through its own capability grant; this boundary blocks the willow-seat bypass.
ORCHESTRATOR_WRITE_TOOLS = frozenset({
    "dispatch_send",
    "verify_handoff",
    "agent_clear",
    "frank_append",
    "envelope_apply",
})


def is_orchestrator_app(app_id: str) -> bool:
    return (app_id or "").strip().lower() == ORCHESTRATOR_APP_ID


def human_orchestrator_attested() -> bool:
    """Host-level signal: MCP process was started for the human orchestrator seat.

    Set WILLOW_HUMAN_ORCHESTRATOR=1 only in the orchestrator workspace MCP config
    (e.g. ~/github/willow/.cursor/mcp.json). Do NOT set on specialist seats.
    """
    return os.environ.get("WILLOW_HUMAN_ORCHESTRATOR", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def require_operator_terminal() -> None:
    """Fail-closed operator-presence gate for local mutation CLIs (Loki §4.3).

    ``sys.stdin.isatty()`` alone is forgeable — an agent process can allocate a
    pty and pass it. This adds two checks a sandboxed or re-parented agent cannot
    satisfy: it must not be running inside the Kart sandbox, and its controlling
    terminal must be owned by the real invoking user. An agent draining tasks has
    no operator-owned controlling tty, so it fails closed here even if it fakes
    isatty().
    """
    import sys

    if os.environ.get("WILLOW_IN_KART", "").strip():
        raise PermissionError("mutation refused inside the Kart sandbox")
    if not sys.stdin.isatty():
        raise PermissionError("mutation requires an interactive operator terminal")
    try:
        terminal = os.ttyname(sys.stdin.fileno())
        owner_uid = os.stat(terminal).st_uid
    except OSError as exc:
        raise PermissionError(f"operator terminal not verifiable: {exc}")
    if owner_uid != os.getuid():
        raise PermissionError(
            "controlling terminal is not owned by the invoking operator"
        )


def orchestrator_write_denial(app_id: str, tool_name: str, *, serve_mode: bool) -> str | None:
    """Return denial reason if this orchestrator write must be blocked, else None."""
    if not is_orchestrator_app(app_id):
        return None
    if tool_name not in ORCHESTRATOR_WRITE_TOOLS:
        return None
    if serve_mode:
        # OAuth identity binding to willow implies a human signed in and confirmed.
        return None
    if human_orchestrator_attested():
        return None
    return (
        "orchestrator_human_required: dispatch_send, verify_handoff, and agent_clear "
        "for app_id=willow require a human orchestrator host "
        "(WILLOW_HUMAN_ORCHESTRATOR=1 on the MCP server env). Agents cannot run Willow."
    )
