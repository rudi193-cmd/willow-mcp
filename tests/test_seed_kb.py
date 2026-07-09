"""Tests for AS-6 KB slice promotion (kb_ingest)."""

import json

import pytest
from psycopg2.extras import Json

from willow_mcp import seed_kb as skb
from willow_mcp import server


def _write_ratified_seed(home, agent_id: str, **overrides):
    seeds = home / "seeds"
    seeds.mkdir(parents=True, exist_ok=True)
    data = {
        "format": "agent_seed_v1",
        "identity": {"agent_id": agent_id, "kind": "specialist", "display_name": agent_id.title()},
        "seed": {
            "instruction": "Build.",
            "ratification": {
                "status": "ratified",
                "ratifier_agent_id": "sean",
                "ratified_at": "2026-07-09T00:00:00Z",
                "sig_path": f"seeds/{agent_id}.json.sig",
            },
        },
        "persona": {"register": "formal", "voice_rules": ["short"]},
        "context": {"active_work": "PR stack", "correction_pattern": "ask first"},
        "gaps": [],
    }
    data.update(overrides)
    (seeds / f"{agent_id}.json").write_text(json.dumps(data) + "\n")


_KNOWLEDGE_COLUMNS = [
    ("id", "text"),
    ("content", "jsonb"),
    ("domain", "text"),
    ("source_type", "text"),
]


class _FakePgCursor:
    def __init__(self, pg):
        self.pg = pg
        self._result = []

    def execute(self, sql, params=None):
        self.pg.executed.append((sql, params))
        if "information_schema.columns" in sql:
            self._result = list(self.pg.columns)
        else:
            self._result = list(self.pg.canned_rows)

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)

    @property
    def rowcount(self):
        return len(self._result) or 1

    def close(self):
        pass


class _FakePg:
    def __init__(self, *, columns=None, canned_rows=None):
        self.columns = columns or _KNOWLEDGE_COLUMNS
        self.canned_rows = canned_rows or []
        self.executed = []

    def cursor(self):
        return _FakePgCursor(self)

    def get_dsn_parameters(self):
        return {"host": "test-host", "dbname": "test-db"}


@pytest.fixture
def writer_app(home):
    app_dir = home / "mcp_apps" / "writer"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["knowledge_write", "schema_admin"]})
    )
    return "writer"


def test_build_kb_atom_work_context(home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    _write_ratified_seed(home, "hanuman")
    out = skb.build_kb_atom("hanuman", slice_name="work_context")
    assert out["ok"] is True
    assert out["source_type"] == "agent_seed"
    assert out["content"]["slice"] == "work_context"
    assert "persona" in out["content"]["body"]
    assert "active_work" in out["content"]["body"]["context"]


def test_build_kb_atom_rejects_pending(home):
    seeds = home / "seeds"
    seeds.mkdir(parents=True)
    data = {
        "format": "agent_seed_v1",
        "identity": {"agent_id": "loki", "kind": "specialist"},
        "seed": {"ratification": {"status": "pending"}},
    }
    (seeds / "loki.json").write_text(json.dumps(data))
    out = skb.build_kb_atom("loki")
    assert out["error"] == "seed_not_ratified"


def test_build_kb_atom_blocks_operator_full(home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    _write_ratified_seed(home, "sean", identity={"agent_id": "sean", "kind": "operator"})
    out = skb.build_kb_atom("sean", slice_name="full")
    assert out["error"] in {"full_slice_denied_for_operator", "preset_denied"}


def test_promote_seed_to_kb_inserts(home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    _write_ratified_seed(home, "jeles")
    fake = _FakePg()
    fields = {
        "id": {"column": "id", "data_type": "text"},
        "content": {"column": "content", "data_type": "jsonb"},
        "domain": {"column": "domain", "data_type": "text"},
        "source": {"column": "source_type", "data_type": "text"},
        "tags": {"column": None, "data_type": None},
    }
    out = skb.promote_seed_to_kb(
        fake, fields, agent_id="jeles", slice_name="voice_only", new_id="AB12CD34"
    )
    assert out["ok"] is True
    assert out["action"] == "created"
    assert out["id"] == "AB12CD34"
    insert_sql, params = fake.executed[-1]
    assert insert_sql.startswith("INSERT INTO knowledge")
    assert isinstance(params[1], Json)
    assert params[1].adapted["kind"] == "agent_seed_v1"


def test_kb_ingest_tool(writer_app, home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    _write_ratified_seed(home, "ada")
    fake = _FakePg()
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    server.schema_confirm_mapping(app_id=writer_app, table="knowledge")

    out = server.kb_ingest(writer_app, "ada", slice="work_context")

    assert out["ok"] is True
    assert out["source_type"] == "agent_seed"
    assert out["slice"] == "work_context"


def test_kb_ingest_refuses_unconfirmed_schema(writer_app, home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    _write_ratified_seed(home, "ada")
    fake = _FakePg()
    monkeypatch.setattr(server, "get_pg", lambda: fake)
    out = server.kb_ingest(writer_app, "ada")
    assert "unconfirmed_schema" in out["error"]
