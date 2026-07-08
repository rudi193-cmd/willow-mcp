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


# ── knowledge_search / kb_at / kb_startup_continuity (schema-adapted, docs/design/schema-adaptation.md §9 step 2) ──
#
# These tools build their SQL from a schema_profile mapping instead of
# hardcoded column names (see tests/test_schema_profile.py for the mapping
# logic itself). These tests exercise the tool-level wiring: gate -> Postgres
# unavailable -> table_not_found -> schema_unusable -> the actual mapped
# query and result shape, using a fake Postgres connection that just enough
# emulates the two query shapes these tools issue (information_schema
# introspection, then the mapped SELECT) to verify both the SQL built and
# the result returned, without touching a real database.

class _FakePgCursor:
    def __init__(self, conn):
        self._conn = conn
        self._result: list = []

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))
        if "information_schema.columns" in sql:
            self._result = list(self._conn.columns)
        else:
            self._result = list(self._conn.canned_rows)

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None

    def close(self):
        pass


class _FakePg:
    """columns: list[(name, data_type)] as information_schema would return.
    canned_rows: list[tuple] returned verbatim for any non-introspection
    query — good enough to test result-shape wiring; SQL-shape assertions
    (which columns, which WHERE clauses) are checked against `.executed`
    directly rather than by emulating real filtering."""

    def __init__(self, columns, canned_rows=None):
        self.columns = columns
        self.canned_rows = canned_rows or []
        self.executed: list = []

    def cursor(self):
        return _FakePgCursor(self)

    def get_dsn_parameters(self):
        return {"host": "test-host", "dbname": "test-db"}


_KNOWLEDGE_COLUMNS_NO_TAGS = [
    ("id", "text"), ("content", "jsonb"), ("domain", "text"), ("source_type", "text"),
]


def test_knowledge_search_empty_query_short_circuits(app_id):
    assert server.knowledge_search(app_id=app_id, query="   ") == {"results": []}


def test_knowledge_search_postgres_unavailable(app_id, monkeypatch):
    monkeypatch.setattr(server, "get_pg", lambda: None)
    assert server.knowledge_search(app_id=app_id, query="hi") == {"error": "postgres_unavailable"}


def test_knowledge_search_table_not_found(app_id, monkeypatch):
    fake = _FakePg(columns=[])
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    result = server.knowledge_search(app_id=app_id, query="hi")
    assert result == {"error": "table_not_found", "table": "knowledge"}


def test_knowledge_search_schema_unusable_without_id_or_content(app_id, monkeypatch):
    fake = _FakePg(columns=[("domain", "text")])
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    result = server.knowledge_search(app_id=app_id, query="hi")
    assert "schema_unusable" in result["error"]


def test_knowledge_search_maps_columns_casts_jsonb_and_returns_shaped_results(app_id, monkeypatch):
    fake = _FakePg(
        columns=_KNOWLEDGE_COLUMNS_NO_TAGS,
        canned_rows=[("A1", {"x": 1}, "general", "session")],
    )
    monkeypatch.setattr(server, "get_pg", lambda: fake)

    result = server.knowledge_search(app_id=app_id, query="hello world", domain="general", limit=5)

    assert result["results"] == [
        {"id": "A1", "content": {"x": 1}, "domain": "general", "source": "session", "tags": None}
    ]
    assert result["_unmapped"] == ["tags"]

    select_sql, params = fake.executed[-1]
    assert '"content"::text ILIKE' in select_sql   # jsonb column cast for ILIKE
    assert '"source_type" AS "source"' in select_sql  # alias mapping applied
    assert '"domain" = %s' in select_sql           # domain filter, since domain is mapped
    assert "tags" not in select_sql                # never reference an unmapped column
    assert params[-2:] == ["general", 5]           # domain filter param, then limit


def test_knowledge_search_skips_domain_filter_when_domain_unmapped(app_id, monkeypatch):
    fake = _FakePg(columns=[("id", "text"), ("content", "jsonb")], canned_rows=[])
    monkeypatch.setattr(server, "get_pg", lambda: fake)

    server.knowledge_search(app_id=app_id, query="hi", domain="general")

    select_sql, params = fake.executed[-1]
    assert "domain" not in select_sql
    assert "general" not in params


def test_knowledge_search_denied_without_permission(tmp_path, monkeypatch):
    apps_root = tmp_path / "mcp_apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    app_dir = apps_root / "writeonly"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(json.dumps({"permissions": ["knowledge_write"]}))

    result = server.knowledge_search(app_id="writeonly", query="hi")
    assert "denied" in result["error"]


def test_kb_at_not_found(app_id, monkeypatch):
    fake = _FakePg(columns=_KNOWLEDGE_COLUMNS_NO_TAGS, canned_rows=[])
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    assert server.kb_at(app_id=app_id, atom_id="ghost") == {"error": "not_found"}


def test_kb_at_found_surfaces_unmapped_and_filters_by_mapped_id_column(app_id, monkeypatch):
    fake = _FakePg(
        columns=_KNOWLEDGE_COLUMNS_NO_TAGS,
        canned_rows=[("A1", {"x": 1}, "general", "session")],
    )
    monkeypatch.setattr(server, "get_pg", lambda: fake)

    result = server.kb_at(app_id=app_id, atom_id="A1")

    assert result["id"] == "A1"
    assert result["tags"] is None
    assert result["_unmapped"] == ["tags"]
    select_sql, params = fake.executed[-1]
    assert 'WHERE "id" = %s' in select_sql
    assert params == ("A1",)


def test_kb_at_schema_unusable_without_id_column(app_id, monkeypatch):
    fake = _FakePg(columns=[("content", "jsonb")])
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    result = server.kb_at(app_id=app_id, atom_id="x")
    assert "schema_unusable" in result["error"]


def test_kb_startup_continuity_uses_domain_only_when_tags_unmapped(app_id, monkeypatch):
    fake = _FakePg(columns=_KNOWLEDGE_COLUMNS_NO_TAGS, canned_rows=[])
    monkeypatch.setattr(server, "get_pg", lambda: fake)

    result = server.kb_startup_continuity(app_id=app_id, limit=5)

    assert result["_unmapped"] == ["tags"]
    where_sql, params = fake.executed[-1]
    assert '"domain" = %s' in where_sql
    assert "tags" not in where_sql
    assert " OR " not in where_sql


def test_kb_startup_continuity_ors_domain_and_tags_when_both_mapped(app_id, monkeypatch):
    fake = _FakePg(columns=_KNOWLEDGE_COLUMNS_NO_TAGS + [("tags", "text")], canned_rows=[])
    monkeypatch.setattr(server, "get_pg", lambda: fake)

    server.kb_startup_continuity(app_id=app_id, limit=5)

    where_sql, params = fake.executed[-1]
    assert '"domain" = %s' in where_sql
    assert '"tags" LIKE %s' in where_sql
    assert " OR " in where_sql


def test_kb_startup_continuity_fails_closed_when_neither_domain_nor_tags_mapped(app_id, monkeypatch):
    fake = _FakePg(columns=[("id", "text"), ("content", "jsonb")])
    monkeypatch.setattr(server, "get_pg", lambda: fake)

    result = server.kb_startup_continuity(app_id=app_id, limit=5)

    assert result["atoms"] == []
    assert "_note" in result
    assert set(result["_unmapped"]) == {"domain", "source", "tags"}
    # only the introspection query ran — no SELECT issued against an
    # unidentifiable continuity condition.
    assert len(fake.executed) == 1


def test_kb_startup_continuity_schema_unusable_without_id_column(app_id, monkeypatch):
    fake = _FakePg(columns=[("domain", "text")])
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    result = server.kb_startup_continuity(app_id=app_id)
    assert "schema_unusable" in result["error"]
