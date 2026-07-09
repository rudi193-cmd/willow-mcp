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
ORCHESTRATOR_WRITE_TOOLS = frozenset({
    "dispatch_send",
    "verify_handoff",
    "agent_clear",
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
