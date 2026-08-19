"""Unit tests for kb_verify.verify_sources and kb_verify.check_health.

These tests mock kb_verify._query_records directly rather than mocking the
underlying schema_profile.resolve/introspect machinery, since the latter
needs real Postgres catalogs. This isolates the behavior under test to the
scoring/flagging logic inside verify_sources and check_health.
"""
from unittest.mock import patch

from willow_mcp import kb_verify


def _rec(id, content="some content", domain="general", source="agent_seed", tags=None):
    return {"id": id, "content": content, "domain": domain, "source": source, "tags": tags}


def _mock_query(records, unmapped=None):
    """Return a _query_records mock result."""
    return {
        "records": records,
        "present": [f for f in ["id", "content", "domain", "source", "tags"] if f not in (unmapped or [])],
        "unmapped": unmapped or [],
        "total": len(records),
    }


# ---------------------------------------------------------------------------
# verify_sources
# ---------------------------------------------------------------------------

@patch("willow_mcp.kb_verify._query_records")
def test_verify_sources_all_sourced(mock_qr):
    mock_qr.return_value = _mock_query([
        _rec("A1"), _rec("A2"), _rec("A3"),
    ])
    result = kb_verify.verify_sources(None, "test_app")
    assert result["outcome"] == "pass"
    assert result["sourced"] == 3
    assert result["unsourced"] == 0


@patch("willow_mcp.kb_verify._query_records")
def test_verify_sources_some_unsourced(mock_qr):
    # 1/6 unsourced (~16.7%) is below the 20% fail threshold -> warn.
    mock_qr.return_value = _mock_query([
        _rec("A1"), _rec("A2"), _rec("A3"), _rec("A4"), _rec("A5"),
        _rec("A6", source=""),
    ])
    result = kb_verify.verify_sources(None, "test_app")
    assert result["outcome"] == "warn"
    assert result["unsourced"] == 1


@patch("willow_mcp.kb_verify._query_records")
def test_verify_sources_many_unsourced(mock_qr):
    mock_qr.return_value = _mock_query([
        _rec("A1"),
        _rec("A2", source=""),
        _rec("A3", source=""),
        _rec("A4", source=""),
        _rec("A5", source=""),
    ])
    result = kb_verify.verify_sources(None, "test_app")
    assert result["outcome"] == "fail"
    assert "below 80%" in result["recommendation"]


@patch("willow_mcp.kb_verify._query_records")
def test_verify_sources_empty_db(mock_qr):
    mock_qr.return_value = _mock_query([])
    result = kb_verify.verify_sources(None, "test_app")
    assert result["outcome"] == "pass"
    assert result["total"] == 0


@patch("willow_mcp.kb_verify._query_records")
def test_verify_sources_source_unmapped(mock_qr):
    mock_qr.return_value = _mock_query([_rec("A1"), _rec("A2")], unmapped=["source"])
    result = kb_verify.verify_sources(None, "test_app")
    assert result["outcome"] == "warn"
    assert "not mapped" in result["recommendation"]


@patch("willow_mcp.kb_verify._query_records")
def test_verify_sources_error_passthrough(mock_qr):
    mock_qr.return_value = {"error": "schema_unusable"}
    result = kb_verify.verify_sources(None, "test_app")
    assert result["error"] == "schema_unusable"


# ---------------------------------------------------------------------------
# check_health
# ---------------------------------------------------------------------------

@patch("willow_mcp.kb_verify._query_records")
def test_check_health_clean(mock_qr):
    mock_qr.return_value = _mock_query([
        _rec("A1", content="alpha"),
        _rec("A2", content="beta"),
        _rec("A3", content="gamma"),
    ])
    result = kb_verify.check_health(None, "test_app")
    assert result["flags"] == []
    assert "healthy" in result["recommendation"]


@patch("willow_mcp.kb_verify._query_records")
def test_check_health_unsourced(mock_qr):
    mock_qr.return_value = _mock_query([
        _rec("A1", content="alpha"),
        _rec("A2", content="beta", source=""),
    ])
    result = kb_verify.check_health(None, "test_app")
    flags = {f["flag"]: f for f in result["flags"]}
    assert "unsourced_records" in flags
    assert flags["unsourced_records"]["count"] == 1


@patch("willow_mcp.kb_verify._query_records")
def test_check_health_domainless(mock_qr):
    mock_qr.return_value = _mock_query([
        _rec("A1", content="alpha"),
        _rec("A2", content="beta", domain=""),
    ])
    result = kb_verify.check_health(None, "test_app")
    flags = {f["flag"]: f for f in result["flags"]}
    assert "domainless_records" in flags
    assert flags["domainless_records"]["count"] == 1


@patch("willow_mcp.kb_verify._query_records")
def test_check_health_duplicates(mock_qr):
    mock_qr.return_value = _mock_query([
        _rec("A1", content="duplicate content here"),
        _rec("A2", content="duplicate content here"),
        _rec("A3", content="unique content"),
    ])
    result = kb_verify.check_health(None, "test_app")
    flags = {f["flag"]: f for f in result["flags"]}
    assert "duplicate_content" in flags
    assert len(result["evidence"]["duplicate_groups"]) == 1


@patch("willow_mcp.kb_verify._query_records")
def test_check_health_multiple_issues(mock_qr):
    mock_qr.return_value = _mock_query([
        _rec("A1", content="alpha"),
        _rec("A2", content="beta", source=""),
        _rec("A3", content="gamma", domain=""),
    ])
    result = kb_verify.check_health(None, "test_app")
    assert len(result["flags"]) >= 2
    assert "issues found" in result["recommendation"]


@patch("willow_mcp.kb_verify._query_records")
def test_check_health_error_passthrough(mock_qr):
    mock_qr.return_value = {"error": "some_error"}
    result = kb_verify.check_health(None, "test_app")
    assert result["error"] == "some_error"
