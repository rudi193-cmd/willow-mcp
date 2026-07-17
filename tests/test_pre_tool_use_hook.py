"""Tests for hooks/pre_tool_use.py's check_bash() — the pure decision logic
behind the PreToolUse hook. Not part of the willow_mcp package (hooks/ is a
sibling directory, not installed with the package), so it's imported by
path rather than via the normal package import.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_HOOK_PATH = Path(__file__).resolve().parents[1] / "hooks" / "pre_tool_use.py"
_spec = importlib.util.spec_from_file_location("pre_tool_use", _HOOK_PATH)
pre_tool_use = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pre_tool_use)


# ── check_bash: blocked patterns ────────────────────────────────────────

@pytest.mark.parametrize("command", [
    'psql $WILLOW_PG_DB -c "select * from knowledge"',
    "sqlite3 $WILLOW_STORE_ROOT/col/store.db 'select * from records'",
    'python3 -c "import psycopg2; psycopg2.connect(dbname=\'willow\')" # WILLOW_PG_DB',
    "sqlite3 ~/.willow/mcp_receipt.db 'select * from receipts'",
])
def test_check_bash_blocks_owned_store_access(command):
    reason = pre_tool_use.check_bash(command)
    assert reason is not None
    assert "willow-mcp" in reason


def test_check_bash_names_knowledge_tools_for_knowledge_table():
    reason = pre_tool_use.check_bash('psql $WILLOW_PG_DB -c "select * from knowledge"')
    assert "knowledge_search" in reason


def test_check_bash_names_store_tools_for_records_table():
    reason = pre_tool_use.check_bash("sqlite3 $WILLOW_STORE_ROOT/col/store.db 'select * from records'")
    assert "store_get" in reason


# ── check_bash: allowed patterns ────────────────────────────────────────

@pytest.mark.parametrize("command", [
    "",
    "git status",
    "psql some_other_db -c 'select 1'",              # psql, but no willow-mcp marker
    "sqlite3 /tmp/unrelated.db 'select 1'",           # sqlite3, but no willow-mcp marker
    "grep -r knowledge src/",                          # 'knowledge' present, but no db client
    "python3 -m pytest tests/",                        # neither client nor marker
])
def test_check_bash_allows_unrelated_commands(command):
    assert pre_tool_use.check_bash(command) is None


# ── main(): stdin/stdout contract ───────────────────────────────────────

def _run_hook(payload: dict) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout.strip()


def test_main_blocks_and_exits_zero():
    code, stdout = _run_hook({
        "tool_name": "Bash",
        "tool_input": {"command": 'psql $WILLOW_PG_DB -c "select * from knowledge"'},
        "session_id": "s1",
    })
    assert code == 0
    decision = json.loads(stdout)
    assert decision["decision"] == "block"
    assert "willow-mcp" in decision["reason"]


def test_main_silent_and_exits_zero_when_allowed():
    code, stdout = _run_hook({
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
        "session_id": "s1",
    })
    assert code == 0
    assert stdout == ""


def test_main_ignores_non_bash_tools():
    code, stdout = _run_hook({
        "tool_name": "Read",
        "tool_input": {"file_path": "/etc/hosts"},
        "session_id": "s1",
    })
    assert code == 0
    assert stdout == ""


# ── check_task_submit: warns on embedded net directives ─────────────────

@pytest.mark.parametrize("task", [
    "echo hi\n# allow_net",
    "curl https://x\n  # allow_net  ",          # worker strips().== matches, so must we
    "echo hi\n# allow_localhost",
    "a\n# allow_net\nb\n# allow_localhost",
])
def test_check_task_submit_warns_on_embedded_directive(task):
    reason = pre_tool_use.check_task_submit({"task": task})
    assert reason is not None
    assert "task_net" in reason


@pytest.mark.parametrize("task", [
    "echo hi",
    "curl https://example.com",
    "python3 -c 'print(1)  # allow_net in a comment, not its own line'",  # not a bare directive line
    "",
])
def test_check_task_submit_allows_clean_tasks(task):
    assert pre_tool_use.check_task_submit({"task": task}) is None


def test_check_task_submit_handles_missing_task_key():
    assert pre_tool_use.check_task_submit({}) is None


def test_is_task_submit_matches_bare_and_mcp_qualified():
    assert pre_tool_use._is_task_submit("task_submit")
    assert pre_tool_use._is_task_submit("mcp__willow-mcp__task_submit")
    assert pre_tool_use._is_task_submit("mcp__willow-mcp-serve__task_submit")
    assert not pre_tool_use._is_task_submit("task_status")
    assert not pre_tool_use._is_task_submit("Bash")


def test_main_warns_on_task_submit_with_directive():
    code, stdout = _run_hook({
        "tool_name": "mcp__willow-mcp__task_submit",
        "tool_input": {"app_id": "x", "task": "echo hi\n# allow_net"},
        "session_id": "s1",
    })
    assert code == 0
    decision = json.loads(stdout)
    assert decision["decision"] == "warn"
    assert "task_net" in decision["reason"]


def test_main_silent_on_clean_task_submit():
    code, stdout = _run_hook({
        "tool_name": "mcp__willow-mcp__task_submit",
        "tool_input": {"app_id": "x", "task": "echo hi"},
        "session_id": "s1",
    })
    assert code == 0
    assert stdout == ""


# ── self-grant guard: an agent may request egress, never confirm it ──────

@pytest.mark.parametrize("command", [
    "willow-mcp grant-net willow --ttl 30m",
    ".venv/bin/python -m willow_mcp grant-net willow --ttl 1h --reason push",
    'python -c "from willow_mcp import lease; lease.grant(\'willow\', 60, issuer=\'me\')"',
    "willow-mcp consent set internet true",
    "willow-mcp consent reconcile",
    "willow-mcp roster sync",
    'python -c "from willow_mcp import consent_admin; consent_admin.set_key(\'internet\', True)"',
    "echo '{}' > ~/.willow/mcp_apps/_net_leases/willow.json",
    "tee $WILLOW_HOME/mcp_apps/_net_leases/willow.json <<< '{}'",
    "sed -i 's/store_read/task_net/' ~/.willow/mcp_apps/willow/manifest.json",
    'jq \'.permissions += ["task_net"]\' m.json > ~/.willow/mcp_apps/willow/manifest.json',
])
def test_check_bash_self_grant_blocks_minting_egress_keys(command):
    reason = pre_tool_use.check_bash_self_grant(command)
    assert reason is not None
    assert "REQUEST egress" in reason


@pytest.mark.parametrize("command", [
    "",
    "willow-mcp net-status",              # reading is not minting
    "willow-mcp revoke-net willow",       # giving up a key is never escalation
    "willow-mcp worker --once",
    "cat ~/.willow/mcp_apps/willow/manifest.json",          # reading a manifest is fine
    "cat $WILLOW_HOME/mcp_apps/_net_leases/willow.json",    # so is reading a lease
    "ls ~/.willow/mcp_apps/_net_leases/",
    'echo "store_read" > ~/.willow/mcp_apps/willow/manifest.json',  # not the egress key
])
def test_check_bash_self_grant_allows_everything_else(command):
    assert pre_tool_use.check_bash_self_grant(command) is None


def test_check_trust_root_write_blocks_a_lease_file():
    reason = pre_tool_use.check_trust_root_write(
        {"file_path": "/home/x/.willow/mcp_apps/_net_leases/willow.json",
         "content": '{"app_id": "willow"}'})
    assert reason is not None
    assert "B-32" in reason


def test_check_trust_root_write_blocks_task_net_into_a_manifest():
    reason = pre_tool_use.check_trust_root_write(
        {"file_path": "/home/x/.willow/mcp_apps/willow/manifest.json",
         "content": '{"permissions": ["task_queue", "task_net"]}'})
    assert reason is not None


def test_check_trust_root_write_allows_an_unrelated_manifest_edit():
    """Editing a manifest is ordinary work. Only the permission that carries
    egress is the agent's to ask for rather than take."""
    assert pre_tool_use.check_trust_root_write(
        {"file_path": "/home/x/.willow/mcp_apps/willow/manifest.json",
         "content": '{"permissions": ["store_read", "knowledge_read"]}'}) is None


def test_check_trust_root_write_allows_ordinary_files():
    for path in ("", "/home/x/src/server.py", "/home/x/.willow/store/col/store.db"):
        assert pre_tool_use.check_trust_root_write({"file_path": path}) is None


def test_check_trust_root_write_reads_edit_shaped_input():
    reason = pre_tool_use.check_trust_root_write(
        {"file_path": "/home/x/.willow/mcp_apps/willow/manifest.json",
         "new_string": '"permissions": ["full_access", "task_net"]'})
    assert reason is not None


def test_main_blocks_a_write_that_mints_a_lease():
    code, stdout = _run_hook({
        "tool_name": "Write",
        "tool_input": {"file_path": "/home/x/.willow/mcp_apps/_net_leases/willow.json",
                       "content": "{}"},
        "session_id": "s1",
    })
    assert code == 0
    assert json.loads(stdout)["decision"] == "block"


def test_main_blocks_a_bash_grant_net():
    code, stdout = _run_hook({
        "tool_name": "Bash",
        "tool_input": {"command": "willow-mcp grant-net willow --ttl 3h"},
        "session_id": "s1",
    })
    assert code == 0
    decision = json.loads(stdout)
    assert decision["decision"] == "block"
    assert "grant-net" in decision["reason"]


def test_check_task_submit_self_grant_blocks_grant_net_in_task_text():
    """Kart task text is shell. The sandbox stops this today via B-14's bound_ro
    mount, but a guard that only works because of a mount option elsewhere is not
    a guard."""
    reason = pre_tool_use.check_task_submit_self_grant(
        {"task": "willow-mcp grant-net willow --ttl 3h"})
    assert reason is not None


def test_check_task_submit_self_grant_allows_ordinary_tasks():
    for task in ("", "echo hi", "git status", "willow-mcp net-status"):
        assert pre_tool_use.check_task_submit_self_grant({"task": task}) is None


def test_main_blocks_a_task_submit_that_smuggles_grant_net():
    code, stdout = _run_hook({
        "tool_name": "mcp__willow-mcp__task_submit",
        "tool_input": {"app_id": "x", "task": "willow-mcp grant-net x --ttl 1h"},
        "session_id": "s1",
    })
    assert code == 0
    assert json.loads(stdout)["decision"] == "block"


def test_main_still_warns_on_directive_when_not_self_granting():
    """The block must not swallow the softer B-21 warning for ordinary tasks."""
    code, stdout = _run_hook({
        "tool_name": "mcp__willow-mcp__task_submit",
        "tool_input": {"app_id": "x", "task": "curl https://x\n# allow_net"},
        "session_id": "s1",
    })
    assert json.loads(stdout)["decision"] == "warn"


def test_main_silent_on_an_ordinary_write():
    code, stdout = _run_hook({
        "tool_name": "Write",
        "tool_input": {"file_path": "/home/x/src/thing.py", "content": "x = 1"},
        "session_id": "s1",
    })
    assert code == 0
    assert stdout == ""


def test_main_handles_empty_and_malformed_stdin_without_crashing():
    for raw in ("", "not json", "{}"):
        proc = subprocess.run(
            [sys.executable, str(_HOOK_PATH)],
            input=raw,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""
