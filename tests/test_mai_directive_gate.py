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
def test_http_ssrf_hosts_blocked_even_with_consent(executor, monkeypatch, url):
    from willow_mcp import consent
    monkeypatch.setattr(consent, "internet_permitted", lambda: True)
    fetched = []
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: fetched.append(a))
    out = parser._handle_http({"url": url}, "", app_id=executor)
    assert fetched == []
    assert "refused" in out["error"]


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
