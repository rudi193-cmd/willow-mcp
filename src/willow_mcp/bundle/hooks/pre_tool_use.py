"""willow-mcp Claude Code hook — PreToolUse.

Four guards:
- Bash reaching for raw psql/psycopg2/sqlite3 against a database or store
  willow-mcp owns, instead of going through the MCP tools (blocks).
- Bash habits that duplicate MCP tools (ls/grep/git-mutation/python-heredoc) —
  warn or block with redirect hints (trimmed from fleet mcp_routing).
- task_submit calls that hand-embed a Kart network directive (`# allow_net`
  / `# allow_localhost`) in the task text — the server strips these (B-21),
  so it does nothing; the correct path is allow_net=True + the task_net
  permission (warns).
- Any tool call that would write the keys authorizing this agent's own egress:
  minting a lease under `mcp_apps/_net_leases/`, running `willow-mcp grant-net`
  (via Bash *or* smuggled into Kart task text), or editing a manifest to add
  `task_net` (blocks).

That third guard is the sudo invariant (FRANK `90e52ab7`) enforced where the
agent actually acts: *a model may REQUEST egress, never CONFIRM it.* It is a
guardrail, not a control — a hook lives in the agent's own harness and an agent
that bypasses it faces no OS-level obstacle on a single-uid host. The control is
`chown` plus `WILLOW_MCP_STRICT_TRUST_ROOT` (B-32). This makes the boundary
visible at the moment it would be crossed, which is where a mistake gets caught
and where a deliberate crossing stops being deniable.

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
# Known limits (this is a tripwire, not an OS control — see module docstring):
# it catches shell-native access via a named client to a marker-bearing target.
# It does NOT catch a write performed inside a `python -c` one-liner (no client
# token / no shell write-verb), an owned store reached by a bare absolute path
# whose collection isn't named knowledge/records, or a DB client not listed
# below. The real control is `chown` + WILLOW_MCP_STRICT_TRUST_ROOT (B-32).
_CLIENT_RE = re.compile(r"\b(psql|psycopg[23]?|asyncpg|pg8000|sqlite3)\b")
_OWNED_MARKER_RE = re.compile(
    r"WILLOW_PG_DB|WILLOW_STORE_ROOT|\bknowledge\b|\brecords\b"
    r"|(?:mcp_receipt|vault|kart|store)\.db"
)

_TOOL_REDIRECTS = {
    "knowledge": "knowledge_search / kb_at / kb_startup_continuity (read) or "
                  "knowledge_ingest / kb_journal / kb_promote (write, requires "
                  "schema_confirm_mapping first)",
    "records": "store_get / store_list / store_search / store_search_all (read) or "
               "store_put / store_update / store_delete (write)",
}

_TASK_SUBMIT = "task_submit(app_id=..., task='…')"
_TASK_SUBMIT_NET = "task_submit(app_id=..., task='…', allow_net=True)"

# Read-only git/gh — allowed on the operator desk (no Kart round-trip).
_GIT_INSPECT_RE = re.compile(
    r"(?:^|&&\s*)git(?:\s+-C\s+\S+)?\s+"
    r"(status|log|diff|show|branch|rev-parse|describe|shortlog|remote|fetch)\b",
    re.IGNORECASE,
)
_GH_INSPECT_RE = re.compile(
    r"(?:^|&&\s*)gh\s+"
    r"(pr\s+(view|list|checks|status|diff)|issue\s+(view|list)|run\s+list|repo\s+view)\b",
    re.IGNORECASE,
)
_GIT_MUTATION_RE = re.compile(
    r"\bgit(?:\s+-C\s+\S+)?\s+"
    r"(add|commit|push|pull|merge|rebase|checkout|switch|restore|reset|clean|"
    r"clone|cherry-pick|revert|stash|tag|worktree\s+(add|remove)|am)\b",
    re.IGNORECASE,
)
_GH_MUTATION_RE = re.compile(
    r"\bgh\s+"
    r"(pr\s+(create|merge|close|ready|review|edit)|issue\s+create|"
    r"repo\s+create|release\s+create)\b",
    re.IGNORECASE,
)

# Shell habits → (decision, hint). Trimmed product port of fleet mcp_routing.BASH_TO_MCP.
_BASH_ROUTING: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"^\s*ls(\s|$)"), "warn",
     f"store_list / store_search for Willow data · filesystem → {_TASK_SUBMIT}"),
    (re.compile(r"^\s*(cat|head|tail)\s"), "warn",
     "Use the IDE Read tool for repo files · shell-only paths → task_submit"),
    (re.compile(r"^\s*psql\s"), "block",
     "knowledge_search / store_search — Postgres via MCP, not shell"),
    (re.compile(r"\bsqlite3\b"), "block",
     "store_get / store_list / store_search — SQLite store via MCP"),
    (re.compile(r"^\s*pwd\s*$"), "warn", "cwd is in context; fleet_status for roots"),
    (re.compile(r"^\s*tree(\s|$)"), "warn", f"directory tree → {_TASK_SUBMIT}"),
    (re.compile(r"\bgit\s+(push|pull)\b"), "block", f"git network → {_TASK_SUBMIT_NET}"),
    (re.compile(
        r"\bgit\s+(add|commit|checkout|merge|rebase|worktree|clone|stash|reset|"
        r"restore|switch|clean|cherry-pick|revert|tag)\b"),
     "block", f"git mutation → {_TASK_SUBMIT}"),
    (re.compile(r"\bgh\s"), "block", f"gh (mutations / net) → {_TASK_SUBMIT_NET}"),
    (re.compile(r"(?i)python3?\s+.*<<"), "block", f"Python heredoc → {_TASK_SUBMIT}"),
    (re.compile(r"(?i)\bgrep\b|\brg\b"), "warn",
     f"knowledge_search / store_search · symbols → code_graph_search · {_TASK_SUBMIT}"),
    (re.compile(r"(?i)\bfind\s"), "warn",
     f"code_graph_search / knowledge_search · {_TASK_SUBMIT}"),
]


def _git_gh_inspect_allowed(command: str) -> bool:
    c = (command or "").strip()
    if not c:
        return False
    if _GIT_MUTATION_RE.search(c) or _GH_MUTATION_RE.search(c):
        return False
    return bool(_GIT_INSPECT_RE.search(c) or _GH_INSPECT_RE.search(c))


def check_bash_routing(command: str) -> Optional[tuple[str, str]]:
    """Return (decision, reason) when a Bash habit should redirect to MCP, else None."""
    if not command or _git_gh_inspect_allowed(command):
        return None
    for pattern, decision, hint in _BASH_ROUTING:
        if pattern.search(command):
            return decision, f"willow-mcp: prefer MCP tools — {hint}"
    if _GIT_MUTATION_RE.search(command) or _GH_MUTATION_RE.search(command):
        return "block", f"willow-mcp: prefer MCP tools — git/gh mutation → {_TASK_SUBMIT}"
    return None


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


def check_task_submit_self_grant(tool_input: dict) -> Optional[str]:
    """Return a block reason if a task's shell text mints an egress key.

    Kart task text is shell, so `task_submit(task="willow-mcp grant-net ...")` is
    the same crossing as running it in Bash. The sandbox happens to stop it today
    (`mcp_apps/` is `bound_ro`, B-14, so the write fails with EROFS) — but a guard
    that only works because of a mount option somewhere else is not a guard.
    """
    return check_bash_self_grant((tool_input or {}).get("task", "") or "")


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


# The egress keys, as they appear on disk. Minting either is the escalation the
# sudo invariant forbids: request and confirm are separate authorities, and the
# agent holds only the first.
_LEASE_DIR_RE = re.compile(r"mcp_apps/_net_leases\b")
# The identity keystore ($WILLOW_HOME/gate/): per-agent HMAC secrets + the trust
# registry. Minting/rotating an identity or a trust ceiling by writing these is
# the same operator-only authority as minting a lease — an agent may request
# standing, never write its own secret (D2). Reading is not blocked.
_KEYSTORE_RE = re.compile(r"gate/(?:secrets\b|registry\.json)")
_GRANT_CMD_RE = re.compile(
    r"\bwillow-mcp\s+(?:grant-net|sign-net-task|register-agent|revoke-agent|rotate-agent|consent\s+(?:set|reconcile)|roster\s+sync)\b"
    r"|\bwillow_mcp\s+(?:grant-net|sign-net-task|register-agent|revoke-agent|rotate-agent)\b"
    r"|\b(?:lease\.grant|sign_envelope|agent_registry\.(?:register_agent|revoke))\s*\("
    r"|\bconsent_admin\.(?:write_consent|set_key|reconcile)\s*\("
    r"|\bfleet_roster\.sync\s*\("
)
_MANIFEST_RE = re.compile(r"mcp_apps/[^/\s\"']+/manifest\.json")
_TASK_NET_RE = re.compile(r"\btask_net\b")
# Reading a lease or a manifest is not escalation — `net-status` and
# `diagnostic_summary` both do it, and blocking `cat` would be the false-positive
# class B-18 removed. Only a command that plausibly *writes* one is the crossing.
_WRITE_VERB_RE = re.compile(r">>?|\b(tee|cp|mv|install|touch|dd|truncate)\b|\bsed\s+-i\b")

_SELF_GRANT_REASON = (
    "willow-mcp: this invokes an operator-only policy mutation or authorizes your "
    "own egress. An agent may REQUEST egress, another grant, or a roster change; it "
    "may never CONFIRM it itself (sudo invariant, FRANK 90e52ab7). Leases, consent "
    "changes, and signed task envelopes are made by the operator, at their own "
    "terminal, with "
    "`willow-mcp grant-net <app_id> --ttl 30m --reason ...`, and `task_net` is "
    "added to a manifest by the operator, not by the app that wants it. "
    "Ask for the grant; do not write the file. (B-32)"
)

_KEYSTORE_REASON = (
    "willow-mcp: this writes the identity keystore ($WILLOW_HOME/gate/ — per-agent "
    "HMAC secrets and the trust registry). Minting or rotating an identity or a "
    "trust ceiling is operator-only, done at the operator's terminal with "
    "`willow-mcp register-agent / rotate-agent / revoke-agent`; no tool and no app "
    "may write its own secret or raise its own trust. An agent may REQUEST "
    "standing, never CONFIRM it (sudo invariant, D2). Reading is fine; writing is not."
)


def check_bash_self_grant(command: str) -> Optional[str]:
    """Block a command that mints a lease/envelope or grants itself task_net.

    Writes only. `cat`ting a lease, `willow-mcp net-status`, and `revoke-net` are
    all fine — reading a key is not holding one, and giving one up is never
    escalation.
    """
    if not command:
        return None
    if _GRANT_CMD_RE.search(command):
        return _SELF_GRANT_REASON
    if not _WRITE_VERB_RE.search(command):
        return None
    if _LEASE_DIR_RE.search(command):
        return _SELF_GRANT_REASON
    if _KEYSTORE_RE.search(command):
        return _KEYSTORE_REASON
    if _MANIFEST_RE.search(command) and _TASK_NET_RE.search(command):
        return _SELF_GRANT_REASON
    return None


def check_trust_root_write(tool_input: dict) -> Optional[str]:
    """Block a Write/Edit that mints a lease, writes an identity secret, or slips
    `task_net` into a manifest."""
    tool_input = tool_input or {}
    path = str(tool_input.get("file_path", "") or "")
    if not path:
        return None
    if _LEASE_DIR_RE.search(path):
        return _SELF_GRANT_REASON
    if _KEYSTORE_RE.search(path):
        return _KEYSTORE_REASON
    if _MANIFEST_RE.search(path):
        # Only the permission that carries egress. Editing a manifest for any
        # other reason is ordinary work and must not be blocked.
        written = " ".join(str(tool_input.get(k, "") or "")
                           for k in ("content", "new_string", "new_str"))
        if _TASK_NET_RE.search(written):
            return _SELF_GRANT_REASON
    return None


def _is_file_write(tool_name: str) -> bool:
    return tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit")


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
        command = tool_input.get("command", "")
        reason = check_bash_self_grant(command) or check_bash(command)
        if reason:
            print(json.dumps({"decision": "block", "reason": reason}))
        else:
            routed = check_bash_routing(command)
            if routed:
                decision, route_reason = routed
                print(json.dumps({"decision": decision, "reason": route_reason}))
    elif _is_file_write(tool_name):
        reason = check_trust_root_write(tool_input)
        if reason:
            print(json.dumps({"decision": "block", "reason": reason}))
    elif _is_task_submit(tool_name):
        blocked = check_task_submit_self_grant(tool_input)
        if blocked:
            print(json.dumps({"decision": "block", "reason": blocked}))
        else:
            reason = check_task_submit(tool_input)
            if reason:
                print(json.dumps({"decision": "warn", "reason": reason}))
    sys.exit(0)


if __name__ == "__main__":
    main()
