"""#161 abuse tests — mai side-effect directives must be deniable, and denied.

Each test is the attack the issue names, asserted to fail without the grant
and to pass authorization checks only with it: @db (arbitrary SQL), @http
(SSRF), @env (secret exfiltration), plus the ungated-internal-render hole.
"""
from __future__ import annotations

import json

import pytest

from willow_mcp.mai import parser


def _write_manifest(apps_root, app_id, permissions, extra=None):
    app_dir = apps_root / app_id
    app_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"permissions": permissions}
    if extra:
        manifest.update(extra)
    (app_dir / "manifest.json").write_text(json.dumps(manifest))


@pytest.fixture
def apps_root(tmp_path, monkeypatch):
    root = tmp_path / "mcp_apps"
    root.mkdir()
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(root))
    parser.invalidate()
    parser._connections.clear()
    yield root
    parser.invalidate()
    parser._connections.clear()


@pytest.fixture
def reader(apps_root):
    """App with read-only mai grant — no directives."""
    _write_manifest(apps_root, "reader", ["markdownai_read"])
    return "reader"


@pytest.fixture
def executor(apps_root):
    """App granted directives, with one allowlisted @connect name."""
    _write_manifest(
        apps_root,
        "executor",
        ["markdownai_read", "markdownai_directives"],
        extra={"mai_connections": ["scratch"]},
    )
    return "executor"


# ── the ungated hole itself ──────────────────────────────────────────

def test_ungated_render_denies_db_and_env(apps_root, monkeypatch):
    """render() with no app_id — every internal/legacy call — is fail-closed."""
    monkeypatch.setenv("WILLOW_PG_DB", "willow")
    doc = (
        "@markdownai v1.0\n"
        "@connect scratch uri=postgresql://x/y\n"
        '@db using=scratch raw="SELECT 1"\n'
        "@env key=WILLOW_PG_DB fallback=denied-env\n"
    )
    out = parser.render(doc)
    assert parser._DIRECTIVE_DENIED in out       # @db refused, loudly
    assert "willow" not in out                    # @env never resolved
    assert "denied-env" in out                    # env degraded to fallback
    assert "scratch" not in parser._connections   # registry not poisoned


def test_reader_grant_still_denies_directives(reader):
    doc = "@markdownai v1.0\n" '@db using=scratch raw="SELECT 1"\n'
    out = parser.render(doc, app_id=reader)
    assert parser._DIRECTIVE_DENIED in out


# ── @db ──────────────────────────────────────────────────────────────────────

def test_db_requires_manifest_allowlisted_connection(executor):
    out = parser._handle_db({"using": "prod", "raw": "SELECT 1"}, "", app_id=executor)
    assert "not allowlisted" in out[0]["error"]


def test_db_denial_is_loud_even_with_on_error(executor):
    """on-error softens query failures, never a refused authorization."""
    out = parser._handle_db(
        {"using": "prod", "raw": "SELECT 1", "on-error": "quiet"}, "", app_id=executor
    )
    assert isinstance(out, list) and "not allowlisted" in out[0]["error"]


def test_db_allowlisted_connection_still_needs_explicit_connect(executor):
    parser._connections.clear()
    out = parser._handle_db({"using": "scratch", "raw": "SELECT 1"}, "", app_id=executor)
    assert "no @connect declared" in out[0]["error"]


def test_db_never_defaults_to_willow_database(executor, monkeypatch):
    """Even fully granted, an empty-URI connection refuses rather than falling
    back to WILLOW_PG_* (#161 ask 2)."""
    connected = []
    monkeypatch.setitem(
        parser._connections, "scratch", parser.Connection("scratch", "postgres", "")
    )
    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", lambda uri: connected.append(uri))
    out = parser._handle_db({"using": "scratch", "raw": "SELECT 1"}, "", app_id=executor)
    assert connected == []
    assert "no @connect declared" in out[0]["error"]


# ── @http ────────────────────────────────────────────────────────────────────

def test_http_denied_without_grant(apps_root):
    out = parser._handle_http({"url": "https://example.com"}, "")
    assert out["error"] == parser._DIRECTIVE_DENIED


def test_http_honors_operator_consent(executor, monkeypatch):
    monkeypatch.setattr(parser, "directives_permitted", lambda a: a == executor)
    from willow_mcp import consent
    monkeypatch.setattr(consent, "internet_permitted", lambda: False)
    out = parser._handle_http({"url": "https://example.com"}, "", app_id=executor)
    assert "consent.internet" in out["error"]


@pytest.fixture
def consenting(executor, monkeypatch):
    """@http past its two gates, with no live DNS and no ambient proxy.

    `web_fetch._proxy_dials_for` reads the environment and skips resolution
    behind a proxy — by design, and it would make every resolution assertion
    below a tautology in the container this suite runs in.
    """
    from willow_mcp import consent, web_fetch
    monkeypatch.setattr(consent, "internet_permitted", lambda: True)
    monkeypatch.setattr(web_fetch.urllib.request, "getproxies", lambda: {})

    def fake(host, port=0, *a, **k):
        if host == "evil.example":            # public name, private answer
            return [(2, 1, 6, "", ("127.0.0.1", port or 0))]
        if host == "feed.example":
            return [(2, 1, 6, "", ("93.184.216.34", port or 0))]
        raise OSError(f"unstubbed lookup of {host!r}")

    monkeypatch.setattr(web_fetch.socket, "getaddrinfo", fake)
    parser.invalidate()
    return executor


def _no_egress(monkeypatch):
    """Fail loudly if anything actually reaches for a transport."""
    import urllib.request

    from willow_mcp import web_fetch
    dialled = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: dialled.append(a))
    monkeypatch.setattr(web_fetch, "_require_requests",
                        lambda: dialled.append("requests"))
    return dialled


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:5432/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "file:///etc/passwd",
    ],
)
def test_http_ssrf_hosts_blocked_even_with_consent(consenting, monkeypatch, url):
    dialled = _no_egress(monkeypatch)
    out = parser._handle_http({"url": url}, "", app_id=consenting)
    assert dialled == []
    assert "refused" in out["error"]


@pytest.mark.parametrize("url,why", [
    ("https://evil.example/x",         "public name whose A record is 127.0.0.1"),
    ("https://2130706433/x",           "127.0.0.1 written as a decimal integer"),
    ("https://0177.0.0.1/x",           "127.0.0.1 written in octal"),
    ("https://100.64.1.1/x",           "RFC6598 CGNAT — cloud and ISP internals"),
    ("https://[::ffff:127.0.0.1]/x",   "IPv4-mapped loopback"),
    ("https://[64:ff9b::a9fe:a9fe]/x", "NAT64-wrapped 169.254.169.254"),
    ("ftp://169.254.169.254/creds",    "not http(s) at all"),
])
def test_the_hosts_the_old_regex_guard_let_through(consenting, monkeypatch, url, why):
    """Every one of these was measured passing `_http_host_blocked`, which was a
    bare hostname regex matched against `urlparse(url).hostname` — a string,
    never resolved — under a docstring that said it blocked SSRF. The guard is
    now `web_fetch.validate_fetch_url`, the same one `willow_web_fetch` uses."""
    dialled = _no_egress(monkeypatch)
    out = parser._handle_http({"url": url}, "", app_id=consenting)
    assert dialled == [], f"dialled anyway: {why}"
    assert "refused" in out["error"], why


def test_a_public_destination_is_still_fetched(consenting, monkeypatch):
    """The other half — a guard that refuses everything is not a guard."""
    from fake_transport import transport

    from willow_mcp import web_fetch
    shim, adapter = transport([(200, {"Content-Type": "application/json"},
                                b'{"ok": true}')])
    monkeypatch.setattr(web_fetch, "_require_requests", lambda: shim)
    out = parser._handle_http({"url": "https://feed.example/data.json"}, "",
                              app_id=consenting)
    assert out == {"ok": True}
    assert adapter.dialled == [("GET", "https://feed.example/data.json")]


def test_http_does_not_follow_a_redirect_to_a_private_host(consenting, monkeypatch):
    """`urllib.request.urlopen(url)` on the default opener follows the chain
    itself, so the one string the old guard checked was the only hop it ever
    saw. Measured: a 302 from a public URL to 169.254.169.254 was followed and
    the credentials came back as the directive's value."""
    from fake_transport import transport

    from willow_mcp import web_fetch
    shim, adapter = transport([
        (302, {"Location": "http://169.254.169.254/latest/meta-data/iam/"}, b""),
        (200, {"Content-Type": "application/json"}, b'{"AccessKeyId": "AKIA"}'),
    ])
    monkeypatch.setattr(web_fetch, "_require_requests", lambda: shim)
    out = parser._handle_http({"url": "https://feed.example/data.json"}, "",
                              app_id=consenting)
    assert "refused" in out["error"]
    assert "169.254.169.254" in out["error"]
    assert len(adapter.dialled) == 1


def test_an_http_body_is_capped(consenting, monkeypatch):
    """`resp.read()` had no bound, so a directive that fetches a JSON endpoint
    could pull an unbounded response into the rendered document."""
    from fake_transport import transport

    from willow_mcp import web_fetch
    shim, adapter = transport([(200, {"Content-Type": "text/plain"},
                                50 * 1024 * 1024)])
    monkeypatch.setattr(web_fetch, "_require_requests", lambda: shim)
    parser._handle_http({"url": "https://feed.example/big"}, "", app_id=consenting)
    read = adapter.raws[-1].read_bytes
    # Absolute first — a bound stated only in terms of the constant under test
    # moves when the constant does, and a 500MB "cap" would still pass.
    assert read < 5 * 1024 * 1024, f"read {read} bytes for one @http directive"
    assert read <= parser._MAX_HTTP_BYTES + web_fetch._CHUNK_BYTES


def test_no_second_host_guard_lives_in_the_parser():
    """The defect was not only that the regex was weak — it was that a third,
    independent opinion about forbidden destinations existed at all, on a
    permission line whose other tools had already been hardened. One policy, or
    the weakest copy sets the ceiling."""
    import ast
    import inspect

    assert not hasattr(parser, "_http_host_blocked")
    assert not hasattr(parser, "_BLOCKED_HTTP_HOST_RE")

    # ast, not a substring search: the comment block that records what used to
    # be here quotes the old regex on purpose, and prose about a deleted guard
    # is not a guard.
    tree = ast.parse(inspect.getsource(parser))
    calls = [
        f"{ast.unparse(node.func)} (line {node.lineno})"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func).split(".")[-1] in ("urlopen", "build_opener",
                                                      "install_opener")
    ]
    assert calls == [], f"a second egress path is back: {calls}"


# ── @env ─────────────────────────────────────────────────────────────────────

def test_env_default_deny_without_allowlist(executor, monkeypatch):
    monkeypatch.setenv("WILLOW_PG_DB", "willow")
    monkeypatch.delenv("WILLOW_MAI_ENV_ALLOW", raising=False)
    doc = "@markdownai v1.0\n@env key=WILLOW_PG_DB fallback=nope\n"
    out = parser.render(doc, app_id=executor)
    assert "willow" not in out
    assert "nope" in out


def test_env_allowlisted_key_resolves(executor, monkeypatch):
    monkeypatch.setenv("DEPLOY_REGION", "us-east-1")
    monkeypatch.setenv("WILLOW_MAI_ENV_ALLOW", "DEPLOY_REGION")
    doc = "@markdownai v1.0\n@env key=DEPLOY_REGION fallback=nope\n"
    out = parser.render(doc, app_id=executor)
    assert "us-east-1" in out


def test_env_secret_shape_denied_even_when_allowlisted(executor, monkeypatch):
    monkeypatch.setenv("WILLOW_PG_PASSWORD", "hunter2")
    monkeypatch.setenv("WILLOW_MAI_ENV_ALLOW", "WILLOW_PG_PASSWORD")
    doc = "@markdownai v1.0\n@env key=WILLOW_PG_PASSWORD fallback=redacted\n"
    out = parser.render(doc, app_id=executor)
    assert "hunter2" not in out
    assert "redacted" in out
