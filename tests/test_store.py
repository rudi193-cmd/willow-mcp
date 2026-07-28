"""Tests for the SQLite Store — aligned with willow-2.0 WillowStore schema."""

import threading

import pytest
from willow_mcp.db import Store, collection_in_scope


@pytest.fixture
def store(tmp_path):
    return Store(store_root=str(tmp_path))


def test_put_and_get(store):
    rid, action = store.put("test", {"title": "hello", "body": "world"})
    result = store.get("test", rid)
    assert result is not None
    assert result["title"] == "hello"
    assert result["_id"] == rid
    assert result["_action"] == "work_quiet"


def test_put_custom_id(store):
    store.put("test", {"msg": "hi"}, record_id="MYID")
    result = store.get("test", "MYID")
    assert result["msg"] == "hi"


def test_put_deviation_flag(store):
    rid, action = store.put("test", {"x": 1}, deviation=0.785)
    assert action == "flag"
    rid2, action2 = store.put("test", {"x": 2}, deviation=1.571)
    assert action2 == "stop"


def test_get_missing(store):
    assert store.get("test", "NOPE") is None


def test_all(store):
    store.put("col", {"v": "a"})
    store.put("col", {"v": "b"})
    store.put("col", {"v": "c"})
    items = store.all("col")
    assert len(items) == 3


def test_update(store):
    rid, _ = store.put("col", {"v": 1})
    store.update("col", rid, {"v": 2})
    result = store.get("col", rid)
    assert result["v"] == 2


def test_search_single_token(store):
    store.put("col", {"content": "the quick brown fox"})
    store.put("col", {"content": "lazy dog"})
    results = store.search("col", "quick")
    assert len(results) == 1
    assert results[0]["content"] == "the quick brown fox"


def test_search_multi_token(store):
    store.put("col", {"type": "failure-log", "domain": "governance"})
    store.put("col", {"type": "failure-log", "domain": "other"})
    results = store.search("col", "failure-log governance")
    assert len(results) == 1
    assert results[0]["domain"] == "governance"


def test_delete(store):
    rid, _ = store.put("col", {"v": "to delete"})
    assert store.delete("col", rid) is True
    assert store.get("col", rid) is None


def test_delete_missing(store):
    assert store.delete("col", "GHOST") is False


# ── the tombstone is durable (box audit P0) ──────────────────────────────────
#
# delete/purge_collection are soft: they set deleted=1 and the row stays in the
# db, invisible to get/all/search/update/stats. put was the one writer that did
# not respect that. It used INSERT OR REPLACE, which in SQLite DELETEs then
# INSERTs, so the omitted `deleted` column silently took its schema default of
# 0 — re-putting a known id undeleted the row AND gave it a fresh created_at.
# Consequences: store_delete was not durable, and a purged row could be
# replaced under the same id with different content and a forged creation time.

def _raw(store, collection, record_id, field):
    """Read a column straight from SQLite, bypassing the `deleted = 0` filter
    every public reader applies — the tombstone's own state is the assertion."""
    conn = store._conn(collection)
    return conn.execute(
        f"SELECT {field} FROM records WHERE id = ?", (record_id,)
    ).fetchone()[0]


def test_put_does_not_resurrect_a_soft_deleted_record(store):
    store.put("col", {"v": "original"}, record_id="ID1")
    created = _raw(store, "col", "ID1", "created_at")
    assert store.delete("col", "ID1") is True

    store.put("col", {"v": "ATTACKER"}, record_id="ID1")

    # the row stays tombstoned and keeps its original creation time, so the
    # write is invisible rather than a resurrection with a fresh provenance
    assert _raw(store, "col", "ID1", "deleted") == 1
    assert _raw(store, "col", "ID1", "created_at") == created
    assert store.get("col", "ID1") is None


def test_purged_collection_stays_purged_under_the_same_id(store):
    """purge_collection is a bulk delete with the same tombstone semantics, so
    a re-put under a purged id must not bring the record back."""
    store.put("col", {"v": "original"}, record_id="ID1")
    assert store.purge_collection("col") == 1

    store.put("col", {"v": "ATTACKER"}, record_id="ID1")

    assert _raw(store, "col", "ID1", "deleted") == 1
    assert store.get("col", "ID1") is None
    assert store.all("col") == []


def test_put_into_a_tombstone_does_not_raise(store):
    """Regression guard on the fix's first shape, which refused the write.

    store_purge_collection is in the `store_write` group and nothing in db.py
    ever sets `deleted` back to 0, so raising here let any app holding
    store_write tombstone a collection and permanently brick every writer that
    uses a stable record_id against it — context_save, human_loop.resolve,
    gaps, forks, lineage, seed_mirror. That trades a forgery for an
    agent-reachable denial of service, and the tombstone holds without it.
    """
    store.put("ctx", {"turn": 1}, record_id="session-1")
    assert store.purge_collection("ctx") == 1

    rid, action = store.put("ctx", {"turn": 2}, record_id="session-1")

    assert rid == "session-1" and action == "work_quiet"
    assert _raw(store, "ctx", "session-1", "deleted") == 1


def test_put_preserves_created_at_across_updates(store):
    """put(record_id=...) is the upsert idiom used by human_loop, lineage, gaps,
    forks, friction, seed_mirror and context_save, so rewriting created_at on
    every update was a live data bug as well as the forgery half of the P0.
    updated_at still advances."""
    store.put("col", {"v": 1}, record_id="ID1")
    first = store.get("col", "ID1")

    store.put("col", {"v": 2}, record_id="ID1")
    second = store.get("col", "ID1")

    assert second["v"] == 2
    assert second["_created"] == first["_created"]
    assert second["_updated"] >= first["_updated"]


def test_put_still_creates_a_fresh_record_normally(store):
    """The guard must not break the ordinary create/upsert path."""
    rid, action = store.put("col", {"v": "new"})
    assert store.get("col", rid)["v"] == "new"
    assert action == "work_quiet"
    store.put("col", {"v": "updated"}, record_id=rid)
    assert store.get("col", rid)["v"] == "updated"


def test_search_empty_query_returns_empty_not_crash(store):
    """Regression for L-AUTH-02 audit sibling L-BUG-01: an empty/whitespace
    query used to build a malformed SQL WHERE clause and raise instead of
    returning results."""
    store.put("col", {"content": "anything"})
    assert store.search("col", "") == []
    assert store.search("col", "   ") == []


def test_search_all_empty_query_returns_empty_not_crash(store):
    store.put("col_a", {"content": "anything"})
    assert store.search_all("") == []


def test_search_all(store):
    store.put("col_a", {"content": "willow is a system"})
    store.put("col_b", {"content": "willow runs on linux"})
    store.put("col_c", {"content": "something else"})
    results = store.search_all("willow")
    assert len(results) == 2
    collections = {r["_collection"] for r in results}
    assert "col_a" in collections
    assert "col_b" in collections


# ── list_collections (factored out of search_all's own enumeration) ─────────

def test_list_collections_empty_store(store):
    assert store.list_collections() == []


def test_list_collections_lists_every_collection(store):
    store.put("col_a", {"x": 1})
    store.put("col_b", {"x": 2})
    assert set(store.list_collections()) == {"col_a", "col_b"}


def test_list_collections_honors_scope(store):
    store.put("myapp_notes", {"x": 1})
    store.put("agents", {"x": 2})
    assert store.list_collections(scope=["myapp_*"]) == ["myapp_notes"]


def test_list_collections_empty_scope_denies_all(store):
    store.put("col_a", {"x": 1})
    assert store.list_collections(scope=[]) == []


def test_list_collections_matches_search_all_enumeration(store):
    """search_all was refactored to call list_collections internally —
    pin that the set of collections it walks didn't change shape."""
    store.put("col_a", {"content": "willow"})
    store.put("col_b", {"content": "willow"})
    assert set(store.list_collections()) == {
        r["_collection"] for r in store.search_all("willow")
    }


def test_put_rejects_path_traversal_collection(store):
    """Regression: Store itself must reject an unsafe collection name,
    independent of server.py's _sanitize() — defense in depth."""
    with pytest.raises(ValueError):
        store.put("../../etc", {"v": 1})


def test_put_rejects_collection_with_slash(store):
    with pytest.raises(ValueError):
        store.put("a/b", {"v": 1})


def test_concurrent_put_does_not_raise(store):
    """Regression for L-CONC-01: concurrent calls against the same collection
    used to share a sqlite3 connection with unsynchronized execute/commit,
    risking 'database is locked' errors under real concurrency."""
    errors = []

    def worker(n):
        try:
            for i in range(20):
                store.put("concurrent", {"n": n, "i": i})
        except Exception as e:  # noqa: BLE001 - we want to see any exception at all
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(store.all("concurrent")) == 8 * 20


# ── collection_in_scope / search_all(scope=...) (B-24 / L-ISO-01) ───────────

def test_collection_in_scope_none_is_unrestricted():
    assert collection_in_scope("anything", None) is True


def test_collection_in_scope_exact_match():
    assert collection_in_scope("mcp_smoke_test", ["mcp_smoke_test"]) is True
    assert collection_in_scope("agents", ["mcp_smoke_test"]) is False


def test_collection_in_scope_prefix_wildcard():
    assert collection_in_scope("myapp_notes", ["myapp_*"]) is True
    assert collection_in_scope("otherapp_notes", ["myapp_*"]) is False


def test_collection_in_scope_empty_list_denies_all():
    assert collection_in_scope("anything", []) is False


def test_search_all_unscoped_sees_everything(store):
    store.put("col_a", {"content": "willow is a system"})
    store.put("col_b", {"content": "willow runs on linux"})
    results = store.search_all("willow")
    assert len(results) == 2


def test_search_all_scope_confines_to_matching_collections(store):
    store.put("myapp_notes", {"content": "willow secrets for myapp"})
    store.put("agents", {"content": "willow fleet roster"})
    results = store.search_all("willow", scope=["myapp_*"])
    assert len(results) == 1
    assert results[0]["_collection"] == "myapp_notes"


def test_search_all_scope_excludes_shared_collections(store):
    # The exact regression this closes: an app scoped to its own collections
    # must not see fleet-shared collections like "agents" via search_all,
    # even though unscoped apps still can (the fleet-sharing default is
    # preserved — see test_search_all_unscoped_sees_everything).
    store.put("agents", {"content": "sensitive fleet roster data"})
    results = store.search_all("sensitive", scope=["myapp_*"])
    assert results == []
