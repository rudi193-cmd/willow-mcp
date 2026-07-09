"""Session-wide test isolation.

willow_mcp.server creates a module-level Store() and ReceiptLog() at import
time, and gate.py resolves its manifest root from WILLOW_MCP_APPS_ROOT/
WILLOW_HOME at call time. Point all of these at a throwaway tmp directory
before any test module can import willow_mcp.server, so the test suite never
touches a real $WILLOW_HOME on the machine running it.
"""
import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="willow_mcp_test_home_")
os.environ.setdefault("WILLOW_HOME", _tmp)
os.environ.setdefault("WILLOW_STORE_ROOT", os.path.join(_tmp, "store"))
os.environ.setdefault("WILLOW_MCP_RECEIPT_DB", os.path.join(_tmp, "mcp_receipt.db"))
os.environ.setdefault("WILLOW_MCP_APPS_ROOT", os.path.join(_tmp, "mcp_apps"))


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Per-test isolated $WILLOW_HOME + aligned mcp_apps/store roots."""
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "mcp_apps"))
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.delenv("WILLOW_HUMAN_ORCHESTRATOR", raising=False)
    return tmp_path
