"""Tests for schema_profile.py — introspection, heuristic mapping, and the
persisted mapping artifact (docs/design/schema-adaptation.md §3.1-§3.4).
"""
import json

import pytest
from willow_mcp import schema_profile as sp


# ── fakes: just enough of the psycopg2 connection/cursor surface ──────────

class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, columns: dict[str, str], host="localhost", dbname="testdb"):
        """columns: {column_name: data_type}, insertion order preserved."""
        self._columns = columns
        self._host = host
        self._dbname = dbname

    def cursor(self):
        rows = list(self._columns.items())
        return _FakeCursor(rows)

    def get_dsn_parameters(self):
        return {"host": self._host, "dbname": self._dbname}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    return tmp_path


KNOWLEDGE_LIKE_COLUMNS = {
    "id": "text",
    "title": "text",
    "summary": "text",
    "content": "jsonb",
    "source_type": "text",
    "domain": "text",
    "created_at": "timestamp with time zone",
}

CANONICAL = ["id", "content", "domain", "source", "tags"]


# ── introspect ──────────────────────────────────────────────────────────

def test_introspect_returns_columns():
    conn = _FakeConn(KNOWLEDGE_LIKE_COLUMNS)
    cols = sp.introspect(conn, "knowledge")
    assert [c.name for c in cols] == list(KNOWLEDGE_LIKE_COLUMNS)
    assert cols[3].data_type == "jsonb"


def test_introspect_empty_table_returns_empty_list():
    conn = _FakeConn({})
    assert sp.introspect(conn, "nonexistent") == []


# ── propose_mapping ─────────────────────────────────────────────────────

def test_propose_mapping_exact_match():
    cols = sp.introspect(_FakeConn(KNOWLEDGE_LIKE_COLUMNS), "knowledge")
    mapping = sp.propose_mapping(cols, CANONICAL)
    assert mapping["id"] == {"column": "id", "tier": "exact", "confidence": 1.0, "data_type": "text"}
    assert mapping["domain"]["tier"] == "exact"


def test_propose_mapping_alias_match():
    cols = sp.introspect(_FakeConn(KNOWLEDGE_LIKE_COLUMNS), "knowledge")
    mapping = sp.propose_mapping(cols, CANONICAL)
    assert mapping["source"]["column"] == "source_type"
    assert mapping["source"]["tier"] == "alias"
    assert mapping["source"]["confidence"] == 0.9


def test_propose_mapping_unmapped_when_no_column_or_alias():
    cols = sp.introspect(_FakeConn(KNOWLEDGE_LIKE_COLUMNS), "knowledge")
    mapping = sp.propose_mapping(cols, CANONICAL)
    assert mapping["tags"] == {"column": None, "tier": "unmapped", "confidence": 0.0, "data_type": None}


def test_propose_mapping_ignores_extra_columns():
    cols = sp.introspect(_FakeConn(KNOWLEDGE_LIKE_COLUMNS), "knowledge")
    mapping = sp.propose_mapping(cols, ["id", "domain"])
    assert set(mapping) == {"id", "domain"}


def test_propose_mapping_is_pure_and_deterministic():
    cols = sp.introspect(_FakeConn(KNOWLEDGE_LIKE_COLUMNS), "knowledge")
    a = sp.propose_mapping(cols, CANONICAL)
    b = sp.propose_mapping(cols, CANONICAL)
    assert a == b


# ── db_fingerprint ──────────────────────────────────────────────────────

def test_db_fingerprint_stable_for_same_host_dbname():
    a = sp.db_fingerprint(_FakeConn(KNOWLEDGE_LIKE_COLUMNS, host="h1", dbname="willow"))
    b = sp.db_fingerprint(_FakeConn({}, host="h1", dbname="willow"))
    assert a == b


def test_db_fingerprint_differs_for_different_dbname():
    a = sp.db_fingerprint(_FakeConn(KNOWLEDGE_LIKE_COLUMNS, host="h1", dbname="willow"))
    b = sp.db_fingerprint(_FakeConn(KNOWLEDGE_LIKE_COLUMNS, host="h1", dbname="other"))
    assert a != b


def test_db_fingerprint_never_leaks_dsn_secrets():
    conn = _FakeConn(KNOWLEDGE_LIKE_COLUMNS, host="h1", dbname="willow")
    fp = sp.db_fingerprint(conn)
    # A fingerprint is a hex digest — by construction it can't contain the
    # raw host/dbname string, but assert the shape anyway as a regression
    # guard against someone later returning the raw key instead of hashing it.
    assert len(fp) == 16
    int(fp, 16)  # raises if it's not hex


# ── mapping artifact persistence ────────────────────────────────────────

def test_resolve_writes_new_unconfirmed_artifact(home):
    conn = _FakeConn(KNOWLEDGE_LIKE_COLUMNS)
    record = sp.resolve(conn, "testapp", "knowledge", CANONICAL)
    assert record["confirmed"] is False
    assert record["schema_version"] == sp.SCHEMA_VERSION
    assert record["fields"]["source"]["column"] == "source_type"

    fp = sp.db_fingerprint(conn)
    path = sp.mapping_path("testapp", fp, "knowledge")
    assert path.exists()
    on_disk = json.loads(path.read_text())
    assert on_disk == record


def test_resolve_table_not_found(home):
    conn = _FakeConn({})
    record = sp.resolve(conn, "testapp", "ghost_table", CANONICAL)
    assert record == {"error": "table_not_found", "table": "ghost_table"}


def test_resolve_confirmed_mapping_wins_over_fresh_heuristic(home):
    conn = _FakeConn(KNOWLEDGE_LIKE_COLUMNS)
    fp = sp.db_fingerprint(conn)
    hand_edited = {
        "schema_version": 1,
        "database": fp,
        "table": "knowledge",
        "discovered_at": "2026-01-01T00:00:00Z",
        "confirmed": True,
        "fields": {
            "id": {"column": "id", "tier": "exact", "confidence": 1.0, "data_type": "text"},
            "content": {"column": "content", "tier": "exact", "confidence": 1.0, "data_type": "jsonb"},
            "domain": {"column": "domain", "tier": "exact", "confidence": 1.0, "data_type": "text"},
            "source": {"column": "source_type", "tier": "alias", "confidence": 0.9, "data_type": "text"},
            "tags": {"column": None, "tier": "unmapped", "confidence": 0.0, "data_type": None},
        },
    }
    sp.save_mapping("testapp", fp, "knowledge", hand_edited)

    record = sp.resolve(conn, "testapp", "knowledge", CANONICAL)
    assert record["confirmed"] is True
    assert record["fields"] == hand_edited["fields"]


def test_resolve_downgrades_confirmed_on_schema_drift(home):
    conn = _FakeConn(KNOWLEDGE_LIKE_COLUMNS)
    fp = sp.db_fingerprint(conn)
    confirmed_but_now_wrong = {
        "schema_version": 1,
        "database": fp,
        "table": "knowledge",
        "discovered_at": "2026-01-01T00:00:00Z",
        "confirmed": True,
        "fields": {
            "id": {"column": "id", "tier": "exact", "confidence": 1.0, "data_type": "text"},
            # 'renamed_col' does not exist in KNOWLEDGE_LIKE_COLUMNS — simulates
            # the host having dropped/renamed a column after confirmation.
            "content": {"column": "renamed_col", "tier": "exact", "confidence": 1.0, "data_type": "text"},
        },
    }
    sp.save_mapping("testapp", fp, "knowledge", confirmed_but_now_wrong)

    record = sp.resolve(conn, "testapp", "knowledge", ["id", "content"])
    assert record["confirmed"] is False
    assert record["schema_drift"] is True
    # re-proposed fresh from the real, current columns
    assert record["fields"]["content"]["column"] == "content"


def test_resolve_unconfirmed_recomputes_without_error(home):
    conn = _FakeConn(KNOWLEDGE_LIKE_COLUMNS)
    first = sp.resolve(conn, "testapp", "knowledge", CANONICAL)
    second = sp.resolve(conn, "testapp", "knowledge", CANONICAL)
    assert first["fields"] == second["fields"]
    assert second["confirmed"] is False


# ── cast_for_ilike ──────────────────────────────────────────────────────

def test_cast_for_ilike_casts_jsonb():
    field = {"column": "content", "data_type": "jsonb"}
    assert sp.cast_for_ilike(field) == '"content"::text'


def test_cast_for_ilike_no_cast_for_text():
    field = {"column": "summary", "data_type": "text"}
    assert sp.cast_for_ilike(field) == '"summary"'


# ── mapping_path / table name safety ────────────────────────────────────

def test_mapping_path_rejects_unsafe_table_name(home):
    with pytest.raises(ValueError):
        sp.mapping_path("testapp", "fingerprint123", "../../etc/passwd")
