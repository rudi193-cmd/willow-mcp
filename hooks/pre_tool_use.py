"""willow-mcp Claude Code hook — PreToolUse.

Guards against reaching for raw psql/psycopg2/sqlite3 (via Bash) against a
database or store willow-mcp owns, instead of going through the MCP tools.
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


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    command = payload.get("tool_input", {}).get("command", "")
    reason = check_bash(command)
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


if __name__ == "__main__":
    main()
