"""Sandbox schema auto-confirm — the three guards, each proven to decline.

The auto-confirm exists to unlock writes on the bootstrap's OWN DDL only;
these tests pin that every escape hatch to an adopted/foreign schema falls
through to the human path (guards 1-3), and that a repo-authored schema
confirms with an auditable confirmed_by marker.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from willow_mcp import sandbox_confirm as sc

_REPO = Path(__file__).resolve().parent.parent
_SCHEMA_DIR = _REPO / "docs" / "schema"


# ── _ddl_columns parsing (pure) ──────────────────────────────────────

def test_ddl_columns_reads_repo_tasks_ddl():
    cols = sc._ddl_columns(_SCHEMA_DIR / "tasks.postgres.sql", "tasks")
    assert cols is not None
    assert {"task_id", "task", "status", "result", "completed_at",
            "claim_owner", "attempts", "retry_at"} <= cols
    # constraint keywords never read as columns
    assert "PRIMARY" not in cols and "primary" not in cols


def test_ddl_columns_reads_repo_knowledge_ddl():
    cols = sc._ddl_columns(_SCHEMA_DIR / "knowledge.postgres.sql", "knowledge")
    assert cols == {"id", "content", "domain", "source", "tags"}


def test_ddl_columns_missing_file_is_none(tmp_path):
    assert sc._ddl_columns(tmp_path / "nope.sql", "tasks") is None


def test_ddl_columns_skips_table_level_constraints(tmp_path):
    ddl = tmp_path / "t.postgres.sql"
    ddl.write_text(
        "CREATE TABLE IF NOT EXISTS t (\n"
        "    a text PRIMARY KEY,\n"
        "    b integer CHECK (b > 0),\n"
        "    PRIMARY KEY (a),\n"
        "    CONSTRAINT c_b UNIQUE (b)\n"
        ");\n"
    )
    assert sc._ddl_columns(ddl, "t") == {"a", "b"}


# ── guard logic against a live sandbox Postgres ────────────────────────────

@pytest.fixture
def apps_root(tmp_path, monkeypatch):
    root = tmp_path / "mcp_apps"
    (root / "testapp").mkdir(parents=True)
    (root / "testapp" / "manifest.json").write_text(
        json.dumps({"permissions": ["task_queue"]})
    )
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(root))
    return root


@pytest.fixture
def pg_available():
    from willow_mcp import db

    db._pg_conn = None
    pg = db.get_pg()
    if pg is None:
        pytest.skip("postgres unavailable via get_pg()")
    return pg


def _decisions_for(results, table):
    return [d for d in results if d["table"] == table]


def test_happy_path_confirms_repo_authored_schema(apps_root, pg_available):
    """Fresh artifacts + repo DDL tables (the bootstrapped sandbox shape)
    confirm, and the artifact says a machine did it."""
    from willow_mcp import schema_profile as sp

    results = sc.auto_confirm(_SCHEMA_DIR, ["testapp"])
    tasks = _decisions_for(results, "tasks")
    assert tasks and tasks[0]["confirmed"], tasks
    fp = sp.db_fingerprint(pg_available)
    artifact = sp.load_mapping("testapp", fp, "tasks")
    assert artifact["confirmed"] is True
    assert artifact["confirmed_by"] == "sandbox-bootstrap"


def test_guard1_human_marked_artifact_untouched(apps_root, pg_available):
    """A human-marked artifact — even unconfirmed — is never overwritten. The
    operator_note is the fingerprint that says a person left it on purpose, so
    guard 1 preserves it rather than re-deriving it."""
    from willow_mcp import schema_profile as sp

    fp = sp.db_fingerprint(pg_available)
    sentinel = {"schema_version": 1, "table": "tasks", "confirmed": False,
                "fields": {}, "operator_note": "left unconfirmed on purpose"}
    sp.save_mapping("testapp", fp, "tasks", sentinel)
    results = sc.auto_confirm(_SCHEMA_DIR, ["testapp"])
    tasks = _decisions_for(results, "tasks")[0]
    assert not tasks["confirmed"] and "guard 1" in tasks["reason"]
    assert sp.load_mapping("testapp", fp, "tasks")["operator_note"] == (
        "left unconfirmed on purpose"
    )


def test_guard1_pristine_placeholder_is_reconfirmed_not_stranded(apps_root, pg_available):
    """A pristine placeholder — exactly what schema_profile.resolve() scatters as
    a discovery side effect — is re-derived and confirmed, not locked as
    unconfirmed by guard 1. This is the warm-container bug: a prior run's
    placeholder must not strand every later run on unconfirmed_schema."""
    from willow_mcp import schema_profile as sp

    fp = sp.db_fingerprint(pg_available)
    placeholder = {
        "schema_version": 1, "database": fp, "table": "tasks",
        "discovered_at": "2026-01-01T00:00:00+00:00", "confirmed": False,
        "fields": {"task_id": {"column": "wrong_guess", "tier": "fuzzy",
                               "confidence": 0.4, "data_type": "text"}},
    }
    sp.save_mapping("testapp", fp, "tasks", placeholder)
    results = sc.auto_confirm(_SCHEMA_DIR, ["testapp"])
    tasks = _decisions_for(results, "tasks")[0]
    assert tasks["confirmed"], tasks
    artifact = sp.load_mapping("testapp", fp, "tasks")
    assert artifact["confirmed"] is True
    assert artifact["confirmed_by"] == "sandbox-bootstrap"


def test_is_pristine_placeholder_discriminates_human_fingerprints():
    """Pure unit contract for the guard-1 discriminator: resolve()'s shape is
    pristine; a confirmation, an override tier, or any extra key is not."""
    base = {"schema_version": 1, "database": "d", "table": "tasks",
            "discovered_at": "t", "confirmed": False,
            "fields": {"task_id": {"column": "task_id", "tier": "exact",
                                   "confidence": 1.0}}}
    assert sc._is_pristine_placeholder(base)
    assert sc._is_pristine_placeholder({**base, "fields": {}})       # empty is fine
    assert sc._is_pristine_placeholder({**base, "schema_drift": True})  # a resolve() key
    assert not sc._is_pristine_placeholder({**base, "confirmed": True})
    assert not sc._is_pristine_placeholder({**base, "operator_note": "mine"})
    assert not sc._is_pristine_placeholder(
        {**base, "fields": {"task_id": {"column": "task_id",
                                        "tier": "confirmed_override"}}})
    assert not sc._is_pristine_placeholder({})   # unrecognizable → fail safe


def test_guard2_non_exact_field_declines(apps_root, pg_available, monkeypatch):
    """One alias-tier field marks an adopted schema — human path."""
    from willow_mcp import schema_profile as sp

    real_resolve = sp.resolve

    def aliased(conn, app_id, table, fields):
        mapping = real_resolve(conn, app_id, table, fields)
        if "error" not in mapping and mapping.get("fields"):
            first = next(iter(mapping["fields"]))
            mapping["fields"][first]["tier"] = "alias"
        return mapping

    monkeypatch.setattr(sp, "resolve", aliased)
    results = sc.auto_confirm(_SCHEMA_DIR, ["testapp"])
    for d in results:
        if d["reason"].startswith("guard 1") or d["reason"] == "table not present":
            continue
        assert not d["confirmed"] and "guard 2" in d["reason"], d


def test_guard3_live_table_differing_from_ddl_declines(
    apps_root, pg_available, monkeypatch
):
    """An adopted table (extra/renamed columns vs repo DDL) — human path."""
    from willow_mcp import schema_profile as sp

    real_introspect = sp.introspect

    def with_extra_column(conn, table):
        cols = real_introspect(conn, table)
        if cols:
            cols = cols + [sp.ColumnInfo(name="legacy_extra", data_type="text")]
        return cols

    monkeypatch.setattr(sp, "introspect", with_extra_column)
    results = sc.auto_confirm(_SCHEMA_DIR, ["testapp"])
    interesting = [
        d for d in results
        if not d["reason"].startswith("guard 1") and d["reason"] != "table not present"
    ]
    assert interesting, results
    for d in interesting:
        assert not d["confirmed"], d
        assert "guard 2" in d["reason"] or "guard 3" in d["reason"], d


def test_postgres_absent_declines_everything(apps_root, monkeypatch):
    from willow_mcp import db

    monkeypatch.setattr(db, "get_pg", lambda: None)
    results = sc.auto_confirm(_SCHEMA_DIR, ["testapp"])
    assert results == [{"table": "*", "app_id": "*", "confirmed": False,
                        "reason": "postgres unavailable"}]
