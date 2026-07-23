"""Regression tests for the mai parser fixes — issues #156, #157, #161, #162."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from willow_mcp.mai import parser  # noqa: E402


# ── #156: @constraint colon form no longer silently dropped ───────────────────

def test_constraint_colon_form_extracted():
    c = parser.extract_constraints("@constraint: never delete\n")
    assert len(c) == 1 and c[0].text == "never delete"


def test_constraint_space_and_severity_still_work():
    c = parser.extract_constraints('@constraint severity="critical" no bypass\n')
    assert len(c) == 1 and c[0].severity == "critical" and c[0].text == "no bypass"


# ── #162: nested @if/@endif resolves innermost-first, no leak ──────────────────

def test_nested_if_does_not_leak_inner_audience():
    doc = ('@if consumer="ai"\nOUTER-START\n'
           '@if consumer="human"\nHUMAN-ONLY\n@endif\n'
           'OUTER-END\n@endif')
    out = parser.apply_conditionals(doc, consumer="ai")
    assert "HUMAN-ONLY" not in out          # inner human block stripped
    assert "OUTER-START" in out and "OUTER-END" in out
    assert "@if" not in out and "@endif" not in out   # no dangling directives


def test_flat_if_still_works():
    assert parser.apply_conditionals('@if consumer="ai"\nKEEP\n@endif', "ai").strip() == "KEEP"
    assert parser.apply_conditionals('@if consumer="human"\nDROP\n@endif', "ai").strip() == ""


# ── #161: directive execution is no longer an open exfil/SSRF/DB surface ───────

def test_env_refuses_secret_shaped_keys():
    for k in ("WILLOW_PG_PASSWORD", "API_KEY", "SESSION_SECRET", "SIGNING_KEY"):
        assert parser._handle_env({"key": k, "fallback": "safe"}, "") == "safe"


def test_env_still_returns_non_secret():
    assert parser._handle_env({"key": "WILLOW_PG_DB", "fallback": "x"}, "") not in ("", "safe")


def test_db_refuses_without_explicit_connect():
    r = parser._handle_db({"raw": "SELECT 1"}, "")
    assert isinstance(r, list) and "refused" in str(r[0])


def test_db_on_error_fallback_when_no_connect():
    r = parser._handle_db({"raw": "SELECT 1", "on-error": "n/a"}, "")
    assert isinstance(r, parser._FallbackResult) and r.value == "n/a"


def test_http_blocks_internal_hosts():
    for u in ("http://localhost:5432", "http://127.0.0.1/", "http://169.254.169.254/latest",
              "http://10.0.0.1/", "file:///etc/passwd"):
        assert "refused" in str(parser._handle_http({"url": u}, ""))
