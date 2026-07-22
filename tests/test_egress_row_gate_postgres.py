"""Postgres witness tests for egress row gate (dispatch 5D9A379D close-out).

Exercises ``_row_blocks_net_authorization`` and ``_consume_row_net_authorization``
against real ``tasks`` rows — no mocks on those helpers. Skips when Postgres is
unreachable (``get_pg()`` returns None).
"""
from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from kartikeya import TaskRow
from psycopg2.extras import Json

from willow_mcp import db, egress_authorization as auth, task_queue as tq
from tests.test_egress_authorization import _signed


@pytest.fixture
def keys(tmp_path):
    private = Ed25519PrivateKey.generate()
    private_path = tmp_path / "operator-private.pem"
    public_path = tmp_path / "operator-public.pem"
    private_path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private_path.chmod(0o600)
    public_path.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def _task_columns():
    return {
        "task_id": "id",
        "status": "status",
        "completed_at": "completed_at",
        "result": "result",
    }


def _task_mapping():
    fields = {
        name: {"column": name, "data_type": "text" if name != "result" else "jsonb"}
        for name in tq._TASK_FIELDS
    }
    fields["task_id"] = {"column": "id", "data_type": "text"}
    fields["result"]["data_type"] = "jsonb"
    return {"confirmed": True, "fields": fields}


@pytest.fixture
def pg_live(monkeypatch):
    db._pg_conn = None
    pg = db.get_pg()
    if pg is None:
        pytest.skip("postgres unavailable via get_pg()")
    monkeypatch.setattr(auth, "_task_table_columns", _task_columns)
    monkeypatch.setattr(tq.sp, "resolve", lambda *a, **k: _task_mapping())
    cur = pg.cursor()
    cur.execute("DELETE FROM tasks")
    pg.commit()
    cur.close()
    yield pg
    cur = pg.cursor()
    cur.execute("DELETE FROM tasks")
    pg.commit()
    cur.close()


@pytest.fixture
def queue(pg_live):
    return tq.WillowMcpTaskQueue(pg_live, "witness-worker")


def _insert_task(
    pg,
    task_id: str,
    *,
    status: str = "pending",
    result=None,
    completed_at=None,
    attempts: int = 0,
    max_attempts: int = 3,
    submitted_by: str = "caller",
    task: str = "curl https://example.com\n# allow_net",
):
    cur = pg.cursor()
    cur.execute(
        """
        INSERT INTO tasks (
            id, task, submitted_by, agent, status, result,
            completed_at, attempts, max_attempts, claim_owner, claimed_at,
            network_authorization
        ) VALUES (%s, %s, %s, 'kart', %s, %s, %s, %s, %s, NULL, NULL, '')
        """,
        (
            task_id,
            task,
            submitted_by,
            status,
            Json(result) if result is not None else None,
            completed_at,
            attempts,
            max_attempts,
        ),
    )
    cur.close()
    pg.commit()


def _permit_row_gate_policy(monkeypatch, keys):
    """Execution policy without mocking row-gate helpers."""
    import os

    monkeypatch.setattr(auth.gate, "permitted", lambda *_: True)
    monkeypatch.setattr(auth.consent, "internet_permitted", lambda: True)
    monkeypatch.setattr(auth.lease, "active", lambda *_: True)
    monkeypatch.setattr(auth.lease, "strict_trust_root", lambda: True)
    monkeypatch.setattr(auth.lease, "self_writable_trust_paths", lambda *_: [])
    monkeypatch.setattr(
        auth.lease, "path_is_self_writable_or_replaceable", lambda *_: False
    )
    monkeypatch.setenv("WILLOW_MCP_EGRESS_PUBLIC_KEY", str(keys[1]))
    real_access = os.access
    monkeypatch.setattr(
        auth.os,
        "access",
        lambda path, mode: False if str(path) == str(keys[1]) else real_access(path, mode),
    )


def _fetch_result(pg, task_id: str):
    cur = pg.cursor()
    cur.execute("SELECT result FROM tasks WHERE id = %s", (task_id,))
    row = cur.fetchone()
    cur.close()
    return row[0] if row else None


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_terminal_row_denies_via_row_blocks(pg_live, keys, monkeypatch, status):
    _permit_row_gate_policy(monkeypatch, keys)
    _insert_task(pg_live, "TERM0001", status=status, result={"done": True})
    assert auth._row_blocks_net_authorization("TERM0001") == "task row is terminal"

    authorizer = auth.ExecutorNetworkAuthorizer()
    row = TaskRow(
        task_id="TERM0001",
        task="curl https://example.com\n# allow_net",
        submitted_by="caller",
        network_authorization=_signed(keys, task_id="TERM0001"),
    )
    assert authorizer(row, row.network_authorization) is False
    assert authorizer.last_error == "task row is terminal"


def test_completed_at_denies_even_when_status_running(pg_live, keys, monkeypatch):
    _permit_row_gate_policy(monkeypatch, keys)
    _insert_task(
        pg_live,
        "CMPD0001",
        status="running",
        completed_at="2026-07-21T00:00:00+00:00",
    )
    assert auth._row_blocks_net_authorization("CMPD0001") == "task row already completed"


def test_first_allow_consumes_marker_second_denies(pg_live, keys, monkeypatch):
    _permit_row_gate_policy(monkeypatch, keys)
    _insert_task(pg_live, "CONS0001", status="running", result=None)

    row = TaskRow(
        task_id="CONS0001",
        task="curl https://example.com\n# allow_net",
        submitted_by="caller",
        network_authorization=_signed(keys, task_id="CONS0001"),
    )
    authorizer = auth.ExecutorNetworkAuthorizer()
    assert authorizer(row, row.network_authorization) is True
    stored = _fetch_result(pg_live, "CONS0001")
    assert stored.get(auth._NET_AUTHORITY_CONSUMED_KEY) is True

    authorizer2 = auth.ExecutorNetworkAuthorizer()
    assert authorizer2(row, row.network_authorization) is False
    assert authorizer2.last_error == "network authorization already consumed for row"


def test_retry_path_clears_consumed_marker(pg_live, queue, keys, monkeypatch):
    _permit_row_gate_policy(monkeypatch, keys)

    task_id = "RETRY001"
    _insert_task(pg_live, task_id, status="running", result=None, attempts=0)
    cur = pg_live.cursor()
    cur.execute(
        "UPDATE tasks SET claim_owner = %s, claimed_at = now() WHERE id = %s",
        (queue.claim_owner, task_id),
    )
    cur.close()
    pg_live.commit()

    row = TaskRow(
        task_id=task_id,
        task="curl https://example.com\n# allow_net",
        submitted_by="caller",
        network_authorization=_signed(keys, task_id=task_id),
    )
    authorizer = auth.ExecutorNetworkAuthorizer()
    assert authorizer(row, row.network_authorization) is True
    assert _fetch_result(pg_live, task_id).get(auth._NET_AUTHORITY_CONSUMED_KEY) is True

    queue.mark_done(task_id, status="failed", result=json.dumps({"error": "timeout"}))
    cur = pg_live.cursor()
    cur.execute("SELECT status, result FROM tasks WHERE id = %s", (task_id,))
    status, result = cur.fetchone()
    cur.close()
    assert status == "pending"
    assert not (result or {}).get(auth._NET_AUTHORITY_CONSUMED_KEY)

    cur = pg_live.cursor()
    cur.execute(
        "UPDATE tasks SET status = 'running', claim_owner = %s, claimed_at = now() "
        "WHERE id = %s",
        (queue.claim_owner, task_id),
    )
    cur.close()
    pg_live.commit()

    authorizer2 = auth.ExecutorNetworkAuthorizer()
    assert authorizer2(row, row.network_authorization) is True
    assert authorizer2.last_error == ""


def test_terminal_row_denied_before_shell_launch(pg_live, keys, monkeypatch):
    from kartikeya import execute as kexec

    _permit_row_gate_policy(monkeypatch, keys)
    _insert_task(pg_live, "RECL0001", status="completed", result={"ok": True})
    launched = []
    monkeypatch.setattr(
        kexec,
        "run_shell_task",
        lambda *_a, **_k: launched.append(True) or ("completed", {}),
    )
    row = TaskRow(
        task_id="RECL0001",
        task="curl https://example.com\n# allow_net",
        submitted_by="caller",
        network_authorization=_signed(keys, task_id="RECL0001"),
    )
    status, result = kexec.execute_task_row(
        row, network_authorizer=auth.ExecutorNetworkAuthorizer()
    )
    assert status == "failed"
    assert "verifier refused" in result["error"]
    assert "task row is terminal" in result["error"]
    assert launched == []
