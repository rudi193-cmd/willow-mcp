"""Tests for server.py's guard pipeline (_sanitize, _check_rate, _guarded) and
the store_* tool endpoints running through it. Previously untested (L-TEST-01).

Runs in stdio mode (the pytest process never sets --serve), so _gate() takes
its original path: app_id comes from the tool call itself, same as before
L-AUTH-02 — that finding is serve-mode-only and is covered separately by
test_identity_binding.py plus the manual serve-mode gate exercises done
during that fix.
"""
import json

import pytest
from willow_mcp import server


@pytest.fixture(autouse=True)
def _fresh_rate_buckets():
    """_buckets is a module-global — reset between tests so rate-limit state
    from one test can't bleed into the next."""
    server._buckets.clear()
    yield
    server._buckets.clear()


@pytest.fixture
def app_id(tmp_path, monkeypatch):
    import os

    apps_root = tmp_path / "mcp_apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    app_dir = apps_root / "testapp"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(json.dumps({"permissions": ["full_access"]}))
    return "testapp"


# ── _sanitize ──────────────────────────────────────────────────────────────

def test_sanitize_strips_null_bytes():
    cleaned, problem = server._sanitize({"content": "hello\x00world"})
    assert problem is None
    assert cleaned["content"] == "helloworld"


def test_sanitize_rejects_oversized_record():
    big = {"blob": "x" * (600 * 1024)}
    cleaned, problem = server._sanitize({"record": big})
    assert problem is not None
    assert "512KB" in problem


def test_sanitize_rejects_path_traversal_collection():
    cleaned, problem = server._sanitize({"collection": "../../etc"})
    assert problem is not None
    assert "path" in problem.lower()


def test_sanitize_rejects_too_many_tags():
    cleaned, problem = server._sanitize({"tags": [f"t{i}" for i in range(40)]})
    assert problem is not None


# ── _check_rate ────────────────────────────────────────────────────────────

def test_check_rate_allows_burst_then_limits():
    ok_count = 0
    for _ in range(15):
        allowed, _ = server._check_rate("rate-test-app")
        if allowed:
            ok_count += 1
    # burst capacity is 10 tokens; the 11th+ immediate call should be limited
    assert ok_count == 10


# ── _guarded / tool pipeline (stdio mode) ──────────────────────────────────

def test_store_put_and_get_round_trip(app_id):
    put_result = server.store_put(app_id=app_id, collection="col", record={"v": 1})
    assert "id" in put_result
    got = server.store_get(app_id=app_id, collection="col", record_id=put_result["id"])
    assert got["v"] == 1


def test_guarded_denies_unpermitted_app_id(tmp_path, monkeypatch):
    apps_root = tmp_path / "mcp_apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    app_dir = apps_root / "readonly"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(json.dumps({"permissions": ["store_read"]}))

    result = server.store_put(app_id="readonly", collection="col", record={"v": 1})
    assert "error" in result
    assert "denied" in result["error"]


def test_guarded_denies_missing_manifest():
    result = server.store_get(app_id="totally-unknown-app", collection="col", record_id="x")
    assert "error" in result
    assert "denied" in result["error"]
