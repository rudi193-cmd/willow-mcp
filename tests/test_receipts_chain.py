"""Receipt-log hash chain (B12).

The audit trail session_reconcile trusts as ground truth was a plain SQLite
table — a same-uid process could delete the rows that show out-of-band use and
reconcile would still read clean. It is now hash-chained (mirrors
governance_ledger); verify() names the first broken link. Pure SQLite, no
Postgres.
"""
import sqlite3

from willow_mcp.receipts import ReceiptLog


def _log(tmp_path):
    return ReceiptLog(db_path=str(tmp_path / "r.db"))


def test_clean_chain_verifies(tmp_path):
    log = _log(tmp_path)
    log.record("app", "store_get", "ok")
    log.record("app", "task_submit", "denied", "net_denied")
    log.record("app", "store_put", "ok")
    v = log.verify()
    assert v["ok"] is True and v["count"] == 3


def test_edited_row_breaks_chain(tmp_path):
    log = _log(tmp_path)
    log.record("app", "store_get", "ok")
    log.record("app", "task_submit", "ok")          # the row a tamperer would hide
    log.record("app", "store_put", "ok")
    # Same-uid tamper: rewrite a recorded outcome directly in the file.
    con = sqlite3.connect(str(tmp_path / "r.db"))
    con.execute("UPDATE receipts SET tool = 'store_get' WHERE id = 2")
    con.commit()
    con.close()
    v = log.verify()
    assert v["ok"] is False and v["broken_at"] == 2 and v["reason"] == "entry_hash mismatch"


def test_deleted_row_breaks_chain(tmp_path):
    log = _log(tmp_path)
    for _ in range(4):
        log.record("app", "task_submit", "ok")
    con = sqlite3.connect(str(tmp_path / "r.db"))
    con.execute("DELETE FROM receipts WHERE id = 2")   # excise a middle receipt
    con.commit()
    con.close()
    v = log.verify()
    # id 3's stored prev_hash now points at the deleted id 2's entry_hash, which
    # no longer matches the walk — the linkage breaks at the first surviving row.
    assert v["ok"] is False and v["broken_at"] == 3 and v["reason"] == "prev_hash linkage"


def test_legacy_rows_are_backfilled_and_verify(tmp_path):
    """A pre-B12 table (no chain columns) is migrated and its history chained on
    open, so an existing install becomes verifiable without losing rows."""
    dbp = tmp_path / "r.db"
    con = sqlite3.connect(str(dbp))
    con.executescript(
        "CREATE TABLE receipts (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
        "app_id TEXT NOT NULL, tool TEXT NOT NULL, outcome TEXT NOT NULL, detail TEXT);")
    con.execute("INSERT INTO receipts (ts, app_id, tool, outcome, detail) "
                "VALUES ('2026-01-01T00:00:00+00:00','app','store_get','ok',NULL)")
    con.execute("INSERT INTO receipts (ts, app_id, tool, outcome, detail) "
                "VALUES ('2026-01-01T00:00:01+00:00','app','store_put','ok',NULL)")
    con.commit()
    con.close()

    log = ReceiptLog(db_path=str(dbp))          # opens, migrates, backfills
    assert log.verify()["ok"] is True
    log.record("app", "task_submit", "ok")      # new rows continue the chain
    v = log.verify()
    assert v["ok"] is True and v["count"] == 3


def test_since_and_tail_still_work_with_chain(tmp_path):
    log = _log(tmp_path)
    log.record("app", "store_get", "ok")
    log.record("other", "store_get", "ok")
    assert [r["tool"] for r in log.tail("app")] == ["store_get"]
    assert log.distinct_tools("app", "2000-01-01T00:00:00+00:00", outcome="ok") == ["store_get"]
