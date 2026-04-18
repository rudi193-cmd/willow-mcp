"""Tests for the SQLite Store."""

import pytest
from willow_mcp.db import Store


@pytest.fixture
def store(tmp_path):
    return Store(store_root=str(tmp_path))


def test_put_and_get(store):
    atom_id = store.put("test", "hello world")
    result = store.get("test", atom_id)
    assert result is not None
    assert result["content"] == "hello world"
    assert result["domain"] == "default"


def test_put_custom_id(store):
    store.put("test", "content", atom_id="MYID")
    result = store.get("test", "MYID")
    assert result["content"] == "content"


def test_get_missing(store):
    assert store.get("test", "NOPE") is None


def test_list(store):
    store.put("col", "a")
    store.put("col", "b")
    store.put("col", "c")
    items = store.list_atoms("col", limit=10)
    assert len(items) == 3


def test_list_by_domain(store):
    store.put("col", "x", domain="alpha")
    store.put("col", "y", domain="beta")
    items = store.list_atoms("col", domain="alpha")
    assert len(items) == 1
    assert items[0]["content"] == "x"


def test_search(store):
    store.put("col", "the quick brown fox")
    store.put("col", "lazy dog")
    results = store.search("col", "quick")
    assert len(results) == 1
    assert "quick" in results[0]["content"]


def test_delete(store):
    atom_id = store.put("col", "to delete")
    assert store.delete("col", atom_id) is True
    assert store.get("col", atom_id) is None


def test_delete_missing(store):
    assert store.delete("col", "GHOST") is False


def test_search_all(store):
    store.put("col_a", "willow is a system")
    store.put("col_b", "willow runs on linux")
    store.put("col_c", "something else")
    results = store.search_all("willow", limit=10)
    assert len(results) == 2
    collections = {r["collection"] for r in results}
    assert "col_a" in collections
    assert "col_b" in collections
