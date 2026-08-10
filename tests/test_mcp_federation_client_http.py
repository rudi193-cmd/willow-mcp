"""Remote (streamable-HTTP) transport for the federated client.

A stdio downstream is a subprocess this process forks; a remote one is a network
peer. The tests split along that difference:

  * the destination guard is tested UNPATCHED, because refusing loopback,
    link-local and private space is the whole point of dialling a name at all;
  * the transport itself is then exercised over a REAL HTTP round trip against
    tests/fixtures/http_mcp_server.py, with the guard patched for that one test
    — the only way to reach a test peer, since a test peer is necessarily on
    127.0.0.1 and the guard correctly refuses it.

Patching the guard to test the transport is only honest because the guard is
tested on its own right above it.
"""
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from willow_mcp import mcp_federation
from willow_mcp import mcp_federation_client as mfc

_FIXTURE = Path(__file__).parent / "fixtures" / "http_mcp_server.py"


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    mfc.shutdown_all()


# ── the destination guard, unpatched ────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:9000/mcp",        # loopback
    "http://localhost:9000/mcp",        # loopback by name
    "http://169.254.169.254/latest/",   # cloud metadata
    "http://[::1]:9000/mcp",            # loopback v6
    "file:///etc/passwd",               # not http(s)
    "",                                 # missing
])
def test_a_dangerous_destination_is_refused(url):
    """Delegated to web_fetch.validate_fetch_url, which RESOLVES names rather
    than pattern-matching them — a public name pointed at 127.0.0.1 is caught."""
    assert mcp_federation.validate_remote_url({"url": url}) is not None


def test_a_public_https_destination_passes():
    assert mcp_federation.validate_remote_url({"url": "https://example.com/mcp"}) is None


def test_ratify_refuses_a_blocked_url(tmp_path, monkeypatch):
    """Caught at the operator's terminal, not on some later call."""
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    spec = mcp_federation.McpServerSpec(
        id="remote", name="remote", command="", transport="streamable-http",
        url="http://127.0.0.1:9000/mcp")
    with pytest.raises(ValueError, match="refusing to ratify"):
        mcp_federation.ratify(spec, ratified_by="operator")


def test_connect_revalidates_rather_than_trusting_ratification(monkeypatch):
    """A name ratified while public can be re-pointed at loopback afterwards
    without the registry changing, so the check runs again at every connect."""
    entry = {"id": "remote", "name": "remote", "transport": "streamable-http",
             "url": "http://169.254.169.254/mcp", "command": ""}
    monkeypatch.setattr("willow_mcp.mcp_federation.get_ratified",
                        lambda sid: entry if sid == "remote" else None)
    with pytest.raises(mfc.FederationClientError, match="refusing to dial"):
        mfc.connect_server("remote")


def test_an_unknown_transport_is_refused_by_name(monkeypatch):
    entry = {"id": "weird", "name": "weird", "transport": "carrier-pigeon",
             "url": "https://example.com", "command": ""}
    monkeypatch.setattr("willow_mcp.mcp_federation.get_ratified",
                        lambda sid: entry if sid == "weird" else None)
    with pytest.raises(mfc.FederationClientError, match="not supported"):
        mfc.connect_server("weird")


@pytest.mark.parametrize("transport,expected", [
    ("streamable-http", True), ("streamable_http", True), ("http", True),
    ("HTTP", True), ("stdio", False), ("", False),
])
def test_http_transport_aliases(transport, expected):
    assert mcp_federation.is_http_transport(transport) is expected


# ── auth header, by env NAME never value ────────────────────────────────────

def test_bearer_is_read_from_a_named_env_var(monkeypatch):
    monkeypatch.setenv("FED_TOKEN_TEST", "s3cr3t")
    entry = {"auth_token_env": "FED_TOKEN_TEST"}
    assert mcp_federation.load_auth_headers(entry) == {"Authorization": "Bearer s3cr3t"}
    assert "s3cr3t" not in json.dumps(entry)   # the registry holds the NAME only


def test_an_unset_token_yields_no_header_rather_than_an_empty_one(monkeypatch):
    """`load_server_env`'s rule: an unset key is absent, not empty-stringed — a
    spec cannot manufacture a credential this process was never given."""
    monkeypatch.delenv("FED_TOKEN_TEST", raising=False)
    assert mcp_federation.load_auth_headers({"auth_token_env": "FED_TOKEN_TEST"}) == {}


def test_no_auth_configured_is_no_headers():
    assert mcp_federation.load_auth_headers({}) == {}


# ── a real HTTP round trip ──────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_peer(monkeypatch):
    """A real streamable-HTTP MCP server on loopback, with the destination guard
    stood down for this test only — see the module docstring."""
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(_FIXTURE), str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            if proc.poll() is not None:
                pytest.fail("http fixture exited before listening")
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail("http fixture never listened")

    entry = {"id": "remote", "name": "remote", "transport": "streamable-http",
             "url": url, "command": ""}
    monkeypatch.setattr("willow_mcp.mcp_federation.get_ratified",
                        lambda sid: entry if sid == "remote" else None)
    monkeypatch.setattr("willow_mcp.mcp_federation.validate_remote_url",
                        lambda e: None)
    try:
        yield "remote"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()


def test_connects_to_a_remote_peer_and_guards_its_listing(http_peer):
    tools = mfc.connect_server(http_peer)
    by_name = {t["name"]: t for t in tools}
    assert {"echo", "suspicious"} <= set(by_name)
    # Decision 4(c) still applies over HTTP: a remote server's descriptions are
    # untrusted input, scanned at listing time.
    assert by_name["suspicious"]["guard_verdict"] == "BLOCKED"
    assert "EXTERNAL DATA START" in by_name["suspicious"]["description"]


def test_calls_a_tool_over_http(http_peer):
    out = mfc.call_tool(http_peer, "echo", {"text": "over the wire"})
    assert "over the wire" in out["content_text"]
    assert out["is_error"] is False


def test_result_time_guard_applies_over_http(http_peer):
    out = mfc.call_tool(http_peer, "suspicious", {})
    assert out["guard_verdict"] == "BLOCKED"
    assert "EXTERNAL DATA START" in out["content_text"]
