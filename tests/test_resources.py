"""Tests for MCP Resource handlers (resources.py).

These test the resource handler functions directly — they are plain sync
functions that return JSON strings, and the decorator registration is
tested by verifying the MCPServer's resource_manager state after register().
"""

import json

import pytest
from willow_mcp.db import Store


@pytest.fixture
def store(tmp_path):
    return Store(store_root=str(tmp_path))


# ── Store resource handler tests ────────────────────────────────────────────


class TestStoreCollectionsResource:
    """store://collections — list all collection names."""

    def test_empty_store(self, store):
        from willow_mcp.resources import register

        # Build a minimal mock MCPServer that captures resource registrations
        registrations = {}

        class FakeMCP:
            def resource(self, uri, **kwargs):
                def decorator(fn):
                    registrations[kwargs.get("name", fn.__name__)] = fn
                    return fn
                return decorator

        fake = FakeMCP()
        register(fake, store)

        fn = registrations["store_collections"]
        result = json.loads(fn())
        assert result == {"collections": [], "count": 0}

    def test_with_collections(self, store):
        from willow_mcp.resources import register

        store.put("notes", {"text": "hello"})
        store.put("tasks", {"title": "do stuff"})

        registrations = {}

        class FakeMCP:
            def resource(self, uri, **kwargs):
                def decorator(fn):
                    registrations[kwargs.get("name", fn.__name__)] = fn
                    return fn
                return decorator

        fake = FakeMCP()
        register(fake, store)

        fn = registrations["store_collections"]
        result = json.loads(fn())
        assert result["count"] == 2
        assert set(result["collections"]) == {"notes", "tasks"}


class TestStoreRecordResource:
    """store://{collection}/records/{record_id} — one record by ID."""

    def test_existing_record(self, store):
        from willow_mcp.resources import register

        rid, _ = store.put("test", {"msg": "hello"}, record_id="REC1")

        registrations = {}

        class FakeMCP:
            def resource(self, uri, **kwargs):
                def decorator(fn):
                    registrations[kwargs.get("name", fn.__name__)] = fn
                    return fn
                return decorator

        fake = FakeMCP()
        register(fake, store)

        fn = registrations["store_record"]
        result = json.loads(fn(collection="test", record_id="REC1"))
        assert result["msg"] == "hello"
        assert result["_id"] == "REC1"

    def test_missing_record(self, store):
        from willow_mcp.resources import register

        registrations = {}

        class FakeMCP:
            def resource(self, uri, **kwargs):
                def decorator(fn):
                    registrations[kwargs.get("name", fn.__name__)] = fn
                    return fn
                return decorator

        fake = FakeMCP()
        register(fake, store)

        fn = registrations["store_record"]
        result = json.loads(fn(collection="test", record_id="NOPE"))
        assert result == {"error": "not_found"}


class TestStoreCollectionListResource:
    """store://{collection}/records — list records in one collection."""

    def test_list_records(self, store):
        from willow_mcp.resources import register

        store.put("items", {"v": "a"})
        store.put("items", {"v": "b"})

        registrations = {}

        class FakeMCP:
            def resource(self, uri, **kwargs):
                def decorator(fn):
                    registrations[kwargs.get("name", fn.__name__)] = fn
                    return fn
                return decorator

        fake = FakeMCP()
        register(fake, store)

        fn = registrations["store_collection_list"]
        result = json.loads(fn(collection="items"))
        assert result["count"] == 2
        values = {r["v"] for r in result["records"]}
        assert values == {"a", "b"}
        assert "truncated" not in result

    def test_empty_collection(self, store):
        from willow_mcp.resources import register

        registrations = {}

        class FakeMCP:
            def resource(self, uri, **kwargs):
                def decorator(fn):
                    registrations[kwargs.get("name", fn.__name__)] = fn
                    return fn
                return decorator

        fake = FakeMCP()
        register(fake, store)

        fn = registrations["store_collection_list"]
        result = json.loads(fn(collection="empty"))
        assert result["records"] == []
        assert result["count"] == 0


# ── Registration tests ──────────────────────────────────────────────────────


class TestRegistration:
    """Verify that register() hooks up the expected resource names/URIs."""

    def test_all_resources_registered(self, store):
        from willow_mcp.resources import register

        registrations = {}
        uris = {}

        class FakeMCP:
            def resource(self, uri, **kwargs):
                def decorator(fn):
                    name = kwargs.get("name", fn.__name__)
                    registrations[name] = fn
                    uris[name] = uri
                    return fn
                return decorator

        fake = FakeMCP()
        register(fake, store)

        expected_names = {
            "kb_atom",
            "store_collections",
            "store_collection_list",
            "store_record",
        }
        assert set(registrations.keys()) == expected_names

    def test_uri_patterns(self, store):
        from willow_mcp.resources import register

        uris = {}

        class FakeMCP:
            def resource(self, uri, **kwargs):
                def decorator(fn):
                    uris[kwargs.get("name", fn.__name__)] = uri
                    return fn
                return decorator

        fake = FakeMCP()
        register(fake, store)

        assert uris["kb_atom"] == "kb://atom/{atom_id}"
        assert uris["store_collections"] == "store://collections"
        assert uris["store_collection_list"] == "store://{collection}/records"
        assert uris["store_record"] == "store://{collection}/records/{record_id}"


# ── KB resource handler tests (Postgres-dependent, skipped without PG) ──────


class TestKbAtomResource:
    """kb://atom/{atom_id} — needs Postgres, so we test the no-PG path."""

    def test_no_postgres(self, store, monkeypatch):
        from willow_mcp import resources

        monkeypatch.setattr(resources, "get_pg", lambda: None)

        registrations = {}

        class FakeMCP:
            def resource(self, uri, **kwargs):
                def decorator(fn):
                    registrations[kwargs.get("name", fn.__name__)] = fn
                    return fn
                return decorator

        fake = FakeMCP()
        resources.register(fake, store)

        fn = registrations["kb_atom"]
        result = json.loads(fn(atom_id="any-id"))
        assert result["error"] == "postgres_unavailable"
