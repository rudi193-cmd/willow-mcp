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

# Force these to the throwaway tmp home — do NOT setdefault. A caller may have
# WILLOW_HOME/WILLOW_STORE_ROOT exported (e.g. willow-mcp's own SessionStart
# hook sets them for every web session); setdefault would silently defer to
# those and run the suite against a real store — polluting it and failing the
# gaps/knowledge tests on accumulated rows. Isolation must not be overridable
# by the ambient environment.
_tmp = tempfile.mkdtemp(prefix="willow_mcp_test_home_")
os.environ["WILLOW_HOME"] = _tmp
os.environ["WILLOW_STORE_ROOT"] = os.path.join(_tmp, "store")
os.environ["WILLOW_MCP_RECEIPT_DB"] = os.path.join(_tmp, "mcp_receipt.db")
os.environ["WILLOW_MCP_APPS_ROOT"] = os.path.join(_tmp, "mcp_apps")

# The same principle applied to the variables that decide GATE OUTCOMES rather
# than paths. The list above pinned where the suite reads and writes; these
# decide what it is allowed to do, and inheriting them makes a test's result a
# property of the machine it ran on.
#
#   WILLOW_MCP_STRICT_TRUST_ROOT — with it set, every gate that consults
#     lease.self_writable_trust_paths() denies, because a pytest tmp_path is
#     always writable by the test uid. That is not a finding, it is the
#     definition of a tmp directory. Six tests across test_server.py failed this
#     way on any install running strict mode, each reporting `trust_root_denied`
#     while claiming to be about network envelope authorization.
#   WILLOW_IN_KART — require_operator_terminal checks this BEFORE isatty, so a
#     suite run inside the Kart sandbox refuses mutations for a different reason
#     than the one the tests name, in different words.
#
# A test that needs either ON sets it itself with monkeypatch.setenv, which
# overrides these — deliberate setters keep working, ambient ones stop deciding.
os.environ.pop("WILLOW_MCP_STRICT_TRUST_ROOT", None)
os.environ.pop("WILLOW_IN_KART", None)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Per-test isolated $WILLOW_HOME + aligned mcp_apps/store roots."""
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "mcp_apps"))
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.delenv("WILLOW_HUMAN_ORCHESTRATOR", raising=False)
    return tmp_path


@pytest.fixture(autouse=True)
def _stub_egress_public_key_for_diagnostics(request, monkeypatch, tmp_path):
    """CI has no ~/.config/willow-mcp/egress keys; most tests call _derive_problems."""
    mod = getattr(request.module, "__name__", "")
    if "test_egress" in mod:
        return
    pub = tmp_path / "egress-stub.pub"
    pub.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(
        "willow_mcp.egress_setup.resolve_public_key_path",
        lambda: pub,
    )
