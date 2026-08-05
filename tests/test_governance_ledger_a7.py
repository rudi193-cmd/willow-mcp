"""Governance-ledger hash coverage (box audit A7).

The frank_ledger digest hashed only event_type + content, so FRANK's ``project``
column could be re-pointed by a direct UPDATE and verify() — re-hashing only
event_type+content — would not notice. v2 covers id + project; verify() accepts
legacy v1 rows so the upgrade doesn't false-flag an un-migrated chain, and
rechain() brings old rows up to v2. Pure + a fake cursor — no Postgres.
"""
from willow_mcp.governance_ledger import (
    GovernanceLedger,
    entry_hash,
    entry_hash_v2,
)


# ── the fix, at the hash: project and id are now covered ────────────────────────
def test_v2_hash_covers_project_and_id():
    base = entry_hash_v2("prev", "id1", "projA", "decision", {"x": 1})
    assert base != entry_hash_v2("prev", "id1", "projB", "decision", {"x": 1})  # project
    assert base != entry_hash_v2("prev", "id2", "projA", "decision", {"x": 1})  # id
    # content is still canonicalized (order-independent), as v1 was
    assert (entry_hash_v2("p", "i", "pr", "d", {"a": 1, "b": 2})
            == entry_hash_v2("p", "i", "pr", "d", {"b": 2, "a": 1}))


# ── a fake frank_ledger, just enough for verify()/rechain() ─────────────────────
class _FakePg:
    def __init__(self, rows):
        self.rows = rows  # list of dicts, in created_at order

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        pass


class _FakeCursor:
    def __init__(self, pg):
        self.pg = pg
        self._result = []

    def execute(self, sql, params=None):
        if "pg_advisory" in sql:
            return
        if sql.startswith("UPDATE"):
            prev_hash, new_hash, row_id = params
            for r in self.pg.rows:
                if r["id"] == row_id:
                    r["prev_hash"], r["hash"] = prev_hash, new_hash
            return
        if sql.startswith("INSERT"):
            # rechain()'s self-documenting marker (#280): id, project,
            # event_type, content-json, prev_hash, hash.
            import json as _json
            rid, proj, et, content, prev_hash, new_hash = params
            self.pg.rows.append({"id": rid, "project": proj,
                                 "event_type": et,
                                 "content": _json.loads(content),
                                 "prev_hash": prev_hash, "hash": new_hash})
            return
        if "prev_hash, hash" in sql:            # verify() select
            self._result = [(r["id"], r["project"], r["event_type"], r["content"],
                             r["prev_hash"], r["hash"]) for r in self.pg.rows]
        else:                                    # rechain() select (id..content, hash)
            self._result = [(r["id"], r["project"], r["event_type"], r["content"],
                             r["hash"]) for r in self.pg.rows]

    def fetchall(self):
        return list(self._result)

    def close(self):
        pass


def _v2_chain(entries):
    rows, prev = [], None
    for rid, proj, et, content in entries:
        h = entry_hash_v2(prev, rid, proj, et, content)
        rows.append({"id": rid, "project": proj, "event_type": et,
                     "content": content, "prev_hash": prev, "hash": h})
        prev = h
    return rows


def _v1_chain(entries):
    rows, prev = [], None
    for rid, proj, et, content in entries:
        h = entry_hash(prev, et, content)            # legacy: project not covered
        rows.append({"id": rid, "project": proj, "event_type": et,
                     "content": content, "prev_hash": prev, "hash": h})
        prev = h
    return rows


ENTRIES = [("a", "proj1", "decision", {"n": 1}),
           ("b", "proj1", "envelope_citation", {"n": 2}),
           ("c", "proj2", "decision", {"n": 3})]


def test_clean_v2_chain_verifies():
    assert GovernanceLedger(_FakePg(_v2_chain(ENTRIES))).verify()["valid"] is True


def test_project_tamper_on_v2_row_is_caught():
    rows = _v2_chain(ENTRIES)
    rows[1]["project"] = "attacker"          # re-point project, leave hash as-is
    r = GovernanceLedger(_FakePg(rows)).verify()
    assert r["valid"] is False and r["broken_at"] == "b"


def test_legacy_v1_chain_still_verifies():
    # backward-compat: a pre-A7 chain is not false-flagged as tampered.
    assert GovernanceLedger(_FakePg(_v1_chain(ENTRIES))).verify()["valid"] is True


def test_rechain_upgrades_v1_to_v2_and_covers_project():
    pg = _FakePg(_v1_chain(ENTRIES))
    led = GovernanceLedger(pg)
    out = led.rechain()
    assert out["migrated"] == len(ENTRIES) and out["count"] == len(ENTRIES)
    assert led.verify()["valid"] is True
    # now project IS covered — tampering a migrated row breaks it
    pg.rows[2]["project"] = "attacker"
    assert led.verify()["valid"] is False
    # rechain is idempotent on an already-v2 chain — and appends NO marker
    # then (#280), so repeated idempotent runs do not grow the chain.
    clean_pg = _FakePg(_v2_chain(ENTRIES))
    clean = GovernanceLedger(clean_pg)
    assert clean.rechain()["migrated"] == 0
    assert len(clean_pg.rows) == len(ENTRIES)
