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
from psycopg2.extras import Json
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

    @property
    def rowcount(self):
        return len(self._result)

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


# ── schema_confirm_mapping and the write-path gate (docs/design/schema-adaptation.md §3.4/§9 step 3) ──
#
# knowledge_ingest / kb_journal / kb_promote must refuse to write until the
# table's mapping is confirmed (schema_confirm_mapping). These tests use the
# same _FakePg double as the read-path tests; confirming and then writing
# against the *same* fake instance keeps db_fingerprint consistent between
# the two calls, the way a real Postgres connection would.

def test_schema_confirm_mapping_unknown_table(app_id, monkeypatch):
    fake = _FakePg(columns=_KNOWLEDGE_COLUMNS_NO_TAGS)
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    result = server.schema_confirm_mapping(app_id=app_id, table="not_a_real_table")
    assert "unknown_table" in result["error"]


def test_schema_confirm_mapping_postgres_unavailable(app_id, monkeypatch):
    monkeypatch.setattr(server, "get_pg", lambda: None)
    result = server.schema_confirm_mapping(app_id=app_id, table="knowledge")
    assert result == {"error": "postgres_unavailable"}


def test_schema_confirm_mapping_marks_confirmed(app_id, monkeypatch):
    fake = _FakePg(columns=_KNOWLEDGE_COLUMNS_NO_TAGS)
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    result = server.schema_confirm_mapping(app_id=app_id, table="knowledge")
    assert result["confirmed"] is True
    assert result["fields"]["source"]["column"] == "source_type"


def test_schema_confirm_mapping_applies_overrides(app_id, monkeypatch):
    fake = _FakePg(columns=_KNOWLEDGE_COLUMNS_NO_TAGS)
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    result = server.schema_confirm_mapping(app_id=app_id, table="knowledge", overrides={"tags": None})
    assert result["fields"]["tags"] == {"column": None, "tier": "unmapped", "confidence": 0.0, "data_type": None}


def test_schema_confirm_mapping_denied_without_schema_admin(tmp_path, monkeypatch):
    apps_root = tmp_path / "mcp_apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    app_dir = apps_root / "writer_only"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(json.dumps({"permissions": ["knowledge_write"]}))

    result = server.schema_confirm_mapping(app_id="writer_only", table="knowledge")
    assert "denied" in result["error"]


def test_knowledge_ingest_refuses_until_confirmed(app_id, monkeypatch):
    fake = _FakePg(columns=_KNOWLEDGE_COLUMNS_NO_TAGS)
    monkeypatch.setattr(server, "get_pg", lambda: fake)

    result = server.knowledge_ingest(app_id=app_id, content="hello")

    assert "unconfirmed_schema" in result["error"]
    # nothing beyond the introspection query ran — no write attempted
    assert len(fake.executed) == 1


def test_knowledge_ingest_writes_mapped_columns_and_casts_jsonb_after_confirm(app_id, monkeypatch):
    fake = _FakePg(columns=_KNOWLEDGE_COLUMNS_NO_TAGS)
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    server.schema_confirm_mapping(app_id=app_id, table="knowledge")

    result = server.knowledge_ingest(app_id=app_id, content="hello world", domain="general", source="session")

    assert "id" in result
    insert_sql, params = fake.executed[-1]
    assert insert_sql.startswith("INSERT INTO knowledge")
    assert '"source_type"' in insert_sql   # alias-mapped column used, not the canonical name
    assert '"tags"' not in insert_sql      # never reference an unmapped column
    # content targets a jsonb column -> must be wrapped for psycopg2 to adapt as JSON
    content_param = params[1]
    assert isinstance(content_param, Json)
    assert content_param.adapted == "hello world"


def test_knowledge_ingest_schema_unusable_when_content_unmapped_even_if_confirmed(app_id, monkeypatch):
    fake = _FakePg(columns=[("id", "text"), ("domain", "text")])
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    server.schema_confirm_mapping(app_id=app_id, table="knowledge")  # confirms with content unmapped

    result = server.knowledge_ingest(app_id=app_id, content="hello")
    assert "schema_unusable" in result["error"]


def test_kb_journal_refuses_until_confirmed(app_id, monkeypatch):
    fake = _FakePg(columns=_KNOWLEDGE_COLUMNS_NO_TAGS)
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    result = server.kb_journal(app_id=app_id, content="note")
    assert "unconfirmed_schema" in result["error"]


def test_kb_journal_forces_domain_journal_and_unions_tags_after_confirm(app_id, monkeypatch):
    fake = _FakePg(columns=_KNOWLEDGE_COLUMNS_NO_TAGS + [("tags", "text")])
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    server.schema_confirm_mapping(app_id=app_id, table="knowledge")

    result = server.kb_journal(app_id=app_id, content="note", tags=["extra"])

    assert result["domain"] == "journal"
    insert_sql, params = fake.executed[-1]
    assert '"tags"' in insert_sql
    assert set(params[-1]) == {"journal", "extra"}


def test_kb_promote_refuses_until_confirmed(app_id, monkeypatch):
    fake = _FakePg(columns=_KNOWLEDGE_COLUMNS_NO_TAGS)
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    result = server.kb_promote(app_id=app_id, atom_id="A1", domain="general")
    assert "unconfirmed_schema" in result["error"]


def test_kb_promote_updates_mapped_columns_after_confirm(app_id, monkeypatch):
    fake = _FakePg(columns=_KNOWLEDGE_COLUMNS_NO_TAGS, canned_rows=[("A1",)])
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    server.schema_confirm_mapping(app_id=app_id, table="knowledge")

    result = server.kb_promote(app_id=app_id, atom_id="A1", domain="archived")

    assert result == {"id": "A1", "domain": "archived"}
    update_sql, params = fake.executed[-1]
    assert 'UPDATE knowledge SET "domain" = %s WHERE "id" = %s' in update_sql
    assert params == ("archived", "A1")


def test_kb_promote_schema_unusable_when_domain_unmapped_even_if_confirmed(app_id, monkeypatch):
    fake = _FakePg(columns=[("id", "text"), ("content", "jsonb")])
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    server.schema_confirm_mapping(app_id=app_id, table="knowledge")

    result = server.kb_promote(app_id=app_id, atom_id="A1", domain="general")
    assert "schema_unusable" in result["error"]


# ── task_submit / task_status / task_list / fleet_health (schema-adapted,
# docs/design/schema-adaptation.md §9 step 5) ──
#
# The real production table is `tasks`, not `kart_task_queue` (confirmed via
# live information_schema introspection 2026-07-08). These tools previously
# hardcoded `kart_task_queue`, which doesn't exist, so every call crashed
# with UndefinedTable. They now go through the same schema_profile mapping
# as the knowledge_* tools.

_TASKS_COLUMNS = [
    ("id", "text"), ("task", "text"), ("submitted_by", "text"), ("agent", "text"),
    ("status", "text"), ("result", "jsonb"), ("created_at", "timestamp with time zone"),
]


def test_task_submit_refuses_until_confirmed(app_id, monkeypatch):
    fake = _FakePg(columns=_TASKS_COLUMNS)
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    result = server.task_submit(app_id=app_id, task="do a thing")
    assert "unconfirmed_schema" in result["error"]
    assert len(fake.executed) == 1  # only the introspection query ran


def test_task_submit_writes_mapped_columns_after_confirm(app_id, monkeypatch):
    fake = _FakePg(columns=_TASKS_COLUMNS)
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    server.schema_confirm_mapping(app_id=app_id, table="tasks")

    result = server.task_submit(app_id=app_id, task="do a thing", agent="kart")

    assert result["status"] == "pending"
    assert "task_id" in result
    insert_sql, params = fake.executed[-1]
    assert insert_sql.startswith("INSERT INTO tasks")
    assert '"id"' in insert_sql          # task_id -> id, alias-mapped
    assert '"submitted_by"' in insert_sql
    assert '"agent"' in insert_sql
    assert params[0] == result["task_id"]


def test_task_status_not_found(app_id, monkeypatch):
    fake = _FakePg(columns=_TASKS_COLUMNS, canned_rows=[])
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    assert server.task_status(app_id=app_id, task_id="ghost") == {"error": "not_found"}


def test_task_status_maps_id_to_task_id_and_surfaces_unmapped(app_id, monkeypatch):
    fake = _FakePg(
        columns=_TASKS_COLUMNS,
        canned_rows=[("T1", "do a thing", "willow", "kart", "pending", None, "2026-07-08")],
    )
    monkeypatch.setattr(server, "get_pg", lambda: fake)

    result = server.task_status(app_id=app_id, task_id="T1")

    assert result["task_id"] == "T1"
    assert result["status"] == "pending"
    assert set(result["_unmapped"]) == {"steps", "completed_at"}
    select_sql, params = fake.executed[-1]
    assert '"id" AS "task_id"' in select_sql
    assert 'WHERE "id" = %s' in select_sql
    assert params == ("T1",)


def test_task_status_table_not_found(app_id, monkeypatch):
    fake = _FakePg(columns=[])
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    result = server.task_status(app_id=app_id, task_id="T1")
    assert result == {"error": "table_not_found", "table": "tasks"}


def test_task_list_filters_by_status_and_agent(app_id, monkeypatch):
    fake = _FakePg(
        columns=_TASKS_COLUMNS,
        canned_rows=[("T1", "x" * 100, "willow", "2026-07-08")],
    )
    monkeypatch.setattr(server, "get_pg", lambda: fake)

    result = server.task_list(app_id=app_id, agent="kart", limit=5)

    assert result["pending"][0]["task_id"] == "T1"
    assert len(result["pending"][0]["task"]) == 80  # truncated
    select_sql, params = fake.executed[-1]
    assert '"status" = \'pending\'' in select_sql
    assert '"agent" = %s' in select_sql
    assert params == ("kart", 5)


def test_fleet_health_counts_by_mapped_status_column(app_id, monkeypatch):
    fake = _FakePg(columns=_TASKS_COLUMNS, canned_rows=[("pending", 3), ("completed", 7)])
    monkeypatch.setattr(server, "get_pg", lambda: fake)

    result = server.fleet_health(app_id=app_id)

    assert result == {"pending": 3, "running": 0, "completed": 7, "failed": 0, "total": 10}
    select_sql, params = fake.executed[-1]
    assert select_sql == 'SELECT "status", COUNT(*) FROM tasks GROUP BY "status"'


def test_fleet_health_table_not_found(app_id, monkeypatch):
    fake = _FakePg(columns=[])
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    result = server.fleet_health(app_id=app_id)
    assert result == {"error": "table_not_found", "table": "tasks"}
