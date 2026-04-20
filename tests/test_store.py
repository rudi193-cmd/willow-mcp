"""Tests for the SQLite Store — aligned with willow-1.7 WillowStore schema."""

import pytest
from willow_mcp.db import Store


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


def test_search_all(store):
    store.put("col_a", {"content": "willow is a system"})
    store.put("col_b", {"content": "willow runs on linux"})
    store.put("col_c", {"content": "something else"})
    results = store.search_all("willow")
    assert len(results) == 2
    collections = {r["_collection"] for r in results}
    assert "col_a" in collections
    assert "col_b" in collections
