"""willow-mcp Claude Code hook — PreToolUse.

Two guards:
- Bash reaching for raw psql/psycopg2/sqlite3 against a database or store
  willow-mcp owns, instead of going through the MCP tools (blocks).
- task_submit calls that hand-embed a Kart network directive (`# allow_net`
  / `# allow_localhost`) in the task text — the server strips these (B-21),
  so it does nothing; the correct path is allow_net=True + the task_net
  permission (warns).
See docs/design/hooks-and-skills.md §4 for the design and scope.

Protocol: reads a JSON object from stdin
({"tool_name": ..., "tool_input": {...}, "session_id": ...}), optionally
prints a JSON decision to stdout ({"decision": "block"|"warn", "reason":
"..."}), always exits 0 — the decision is the printed JSON, not the exit
code. No output means allow, no comment.
"""
import json
import re
import sys
from typing import Optional

# Matches a shell client (psql, or a python -c reaching for psycopg2/sqlite3)
# together with something naming a willow-mcp-owned store: the WILLOW_PG_DB/
# WILLOW_STORE_ROOT env var names themselves, or the literal table/path
# willow-mcp creates (knowledge, records, mcp_receipt.db). A bare `sqlite3`
# or `psql` invocation with no such marker isn't ours to block — the host
# may have unrelated databases.
_CLIENT_RE = re.compile(r"\b(psql|psycopg2|sqlite3)\b")
_OWNED_MARKER_RE = re.compile(
    r"WILLOW_PG_DB|WILLOW_STORE_ROOT|\bknowledge\b|\brecords\b|mcp_receipt\.db"
)

_TOOL_REDIRECTS = {
    "knowledge": "knowledge_search / kb_at / kb_startup_continuity (read) or "
                  "knowledge_ingest / kb_journal / kb_promote (write, requires "
                  "schema_confirm_mapping first)",
    "records": "store_get / store_list / store_search / store_search_all (read) or "
               "store_put / store_update / store_delete (write)",
}


def check_bash(command: str) -> Optional[str]:
    """Return a block reason if `command` reaches for a willow-mcp-owned
    store via a raw shell client, else None (allow)."""
    if not command:
        return None
    if not _CLIENT_RE.search(command):
        return None
    if not _OWNED_MARKER_RE.search(command):
        return None

    client = _CLIENT_RE.search(command).group(1)
    for marker, redirect in _TOOL_REDIRECTS.items():
        if marker in command:
            return (
                f"willow-mcp: direct {client} access to its own store is blocked — "
                f"use the MCP tools instead ({redirect})."
            )
    return (
        f"willow-mcp: direct {client} access to a willow-mcp-owned store is "
        f"blocked — use the matching MCP tool (store_*, knowledge_*, kb_*) instead."
    )


# Kart network directives the willow-2.0 worker honors — matched exactly as the
# worker does (core/kart_sandbox.py: `line.strip() == <directive>`). task_submit
# strips any caller-supplied occurrence unconditionally (B-21), so embedding one
# is a no-op; this guard tells the caller that before the call is made.
_NET_DIRECTIVES = {"# allow_net", "# allow_localhost"}


def check_task_submit(tool_input: dict) -> Optional[str]:
    """Return a warn reason if a task_submit call hand-embeds a Kart network
    directive in its task text, else None (allow). This never blocks — the
    server safely strips the directive; the warning steers the caller to the
    real path (allow_net=True + task_net permission)."""
    task = (tool_input or {}).get("task", "") or ""
    embedded = sorted({
        line.strip() for line in task.splitlines() if line.strip() in _NET_DIRECTIVES
    })
    if not embedded:
        return None
    directives = ", ".join(f"`{d}`" for d in embedded)
    return (
        f"willow-mcp: {directives} embedded in task text is ignored — the server "
        "strips Kart network directives from caller-supplied task text (B-21). To "
        "run a task with network egress, pass allow_net=True and grant the "
        "'task_net' permission in the app's manifest (not part of task_queue or "
        "full_access). '# allow_localhost' cannot be self-granted at all."
    )


def _is_task_submit(tool_name: str) -> bool:
    # Matches the bare tool name and the MCP-qualified form
    # (e.g. mcp__willow-mcp__task_submit / mcp__willow-mcp-serve__task_submit).
    return tool_name == "task_submit" or tool_name.endswith("__task_submit")


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    if tool_name == "Bash":
        reason = check_bash(tool_input.get("command", ""))
        if reason:
            print(json.dumps({"decision": "block", "reason": reason}))
    elif _is_task_submit(tool_name):
        reason = check_task_submit(tool_input)
        if reason:
            print(json.dumps({"decision": "warn", "reason": reason}))
    sys.exit(0)


if __name__ == "__main__":
    main()
