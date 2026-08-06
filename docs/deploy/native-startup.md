# Native startup (decommission §1d)

Supported clients (**Cursor**, **Claude Code**) boot through **one path**:

1. **SessionStart** hook → `python -m willow_mcp.session_start_hook`
2. Hook calls **`session_enter`** (MCP server logic, in-process) — not fylgja, not a persona picker, no boot-done sentinels.
3. Hook attaches **`boot_context`**: corrections lanes, stack snapshot from the last **sessionEnd**, degraded verdict, continuation dedup on `compact`/`resume`.

**SessionEnd** → `python -m willow_mcp.session_stop_hook` writes the stack snapshot when the agent skips `session_handoff_write`.

## Materialize local IDE files

From a willow-mcp install with `WILLOW_HOME` set:

```bash
willow-mcp project sync willow
```

Charter repo (`~/github/willow`): refreshes gitignored `.cursor/hooks.json`, `.cursor/mcp.json`, `.claude/settings.local.json`, `.mcp.json`, Codex fragment, and `.willow/active-agent` from `src/willow_mcp/deploy/*`.

After changing hook templates in willow-mcp, **re-run sync** on every seat that uses those projects.

`./willow.sh project sync willow` (willow-2.0) delegates **willow** and **github** registry entries to `willow_mcp.mcp_projects` when the package is installed.

## Cold-open checklist

- SessionStart JSON includes `entry_mode`, `orientation` (handoff, stack_snapshot, records), and `boot_context`.
- No interactive persona gate in the hook path.
- PreToolUse / beforeShellExecution still route Bash → MCP via `pre_tool_hook`.
