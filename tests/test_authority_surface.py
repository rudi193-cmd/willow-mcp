"""Structural guards for the sudo invariant and hook integrity.

These assert, from source, the invariants the willow-gate seam relies on but that
were previously only prose + code review:
  * the two PreToolUse hook copies never drift,
  * no operator-authority verb is reachable as an MCP tool or via any permission
    group (an agent may REQUEST standing/egress, never CONFIRM it).
"""
import re
from pathlib import Path

from willow_mcp import gate

_ROOT = Path(__file__).resolve().parents[1]
_SERVER = _ROOT / "src" / "willow_mcp" / "server.py"
_HOOK = _ROOT / "hooks" / "pre_tool_use.py"
_BUNDLE_HOOK = _ROOT / "src" / "willow_mcp" / "bundle" / "hooks" / "pre_tool_use.py"

# Verbs that mint authority — identity/trust secrets, egress, consent, roster.
# None may be an MCP tool or live inside any permission group.
_AUTHORITY_TOOLS = {
    "register_agent", "revoke_agent", "rotate_agent",
    "grant_net", "sign_net_task", "revoke_net",
    "write_consent", "set_key", "reconcile",
}


def _mcp_tool_names() -> set[str]:
    """Every function directly decorated @mcp.tool() in server.py, read from
    source (importing server pulls in a heavy runtime)."""
    src = _SERVER.read_text(encoding="utf-8")
    return set(re.findall(r"@mcp\.tool\(\)\s*(?:@_guarded\([^\n]*\)\s*)?def\s+([a-zA-Z0-9_]+)", src))


def test_hook_and_bundle_copy_are_byte_identical():
    """The deployed guard is the bundle copy; the tests import the repo-root copy.
    If they diverge, every guard test still passes against a file that isn't the
    one shipped. Keep them identical."""
    assert _HOOK.read_bytes() == _BUNDLE_HOOK.read_bytes()


def test_no_registry_mutation_is_an_mcp_tool():
    tools = _mcp_tool_names()
    assert tools, "sanity: found no @mcp.tool functions — regex likely broke"
    leaked = tools & _AUTHORITY_TOOLS
    assert not leaked, f"authority verbs exposed as MCP tools: {sorted(leaked)}"
    # the seam's identity tools ARE tools, and must stay read/observe-only
    assert "session_bind" in tools and "session_reconcile" in tools


def test_no_authority_verb_lives_in_any_permission_group():
    for group, tools in gate.PERMISSION_GROUPS.items():
        leaked = set(tools) & _AUTHORITY_TOOLS
        assert not leaked, f"permission group {group!r} contains authority verb(s): {sorted(leaked)}"


def test_egress_tools_stay_off_full_access():
    # integration_call / task_net are own-line grants, never bundled into full_access.
    fa = gate.PERMISSION_GROUPS["full_access"]
    assert "integration_call" not in fa
    assert gate.NET_PERMISSION not in fa and gate.INTEGRATION_NET_PERMISSION not in fa
