"""Tests for import-time CLI host/port resolution.

The FastMCP object, base URL, and OAuth issuer are all constructed at module
import — before main()'s argparse runs — so --port/--host must be read from
sys.argv at import (via _argv_opt) or the flags are silently ignored and only
WILLOW_MCP_PORT / WILLOW_MCP_HOST take effect. Regression guard for that bug.
"""
import subprocess
import sys
import textwrap

from willow_mcp import server


# ── _argv_opt (pure) ─────────────────────────────────────────────────────────

def test_argv_opt_space_form(monkeypatch):
    monkeypatch.setattr(server.sys, "argv", ["prog", "--port", "8799"])
    assert server._argv_opt("--port") == "8799"


def test_argv_opt_equals_form(monkeypatch):
    monkeypatch.setattr(server.sys, "argv", ["prog", "--host=0.0.0.0"])
    assert server._argv_opt("--host") == "0.0.0.0"


def test_argv_opt_absent_returns_none(monkeypatch):
    monkeypatch.setattr(server.sys, "argv", ["prog", "--serve"])
    assert server._argv_opt("--port") is None


def test_argv_opt_trailing_flag_without_value(monkeypatch):
    monkeypatch.setattr(server.sys, "argv", ["prog", "--port"])
    assert server._argv_opt("--port") is None


# ── end-to-end import wiring (subprocess, fresh argv) ────────────────────────

def _import_with(argv_tail, env=None):
    """Import server in a subprocess with a controlled sys.argv, print the
    resolved values. Returns (port, host, base_url, settings_port, settings_host)."""
    code = textwrap.dedent(
        f"""
        import sys
        sys.argv = ["willow_mcp"] + {argv_tail!r}
        from willow_mcp import server as s
        print(s._PORT)
        print(s._HOST)
        print(s._BASE_URL)
        print(s.mcp.settings.port)
        print(s.mcp.settings.host)
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env
    ).stdout.split()
    return out[0], out[1], out[2], out[3], out[4]


def test_cli_flags_reach_fastmcp_and_base_url():
    port, host, base_url, s_port, s_host = _import_with(["--port", "8799", "--host", "0.0.0.0"])
    assert port == "8799"
    assert host == "0.0.0.0"
    assert base_url == "http://0.0.0.0:8799"
    assert s_port == "8799"
    assert s_host == "0.0.0.0"


def test_cli_flag_overrides_env():
    import os

    env = dict(os.environ, WILLOW_MCP_PORT="8765")
    port, *_ , s_port, _ = _import_with(["--port", "8799"], env=env)
    assert port == "8799"  # CLI flag wins over WILLOW_MCP_PORT
    assert s_port == "8799"


def test_default_port_when_no_flag_or_env():
    import os

    env = {k: v for k, v in os.environ.items() if k not in ("WILLOW_MCP_PORT", "WILLOW_MCP_HOST")}
    port, host, *_ = _import_with([], env=env)
    assert port == "8765"
    assert host == "127.0.0.1"
