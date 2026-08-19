"""Tests for Store.query_paginated and Store.all_paginated.

Covers SQL-level keyset pagination, multi-column sort, json_extract
filters, cursor encode/decode round-trips, and edge cases (empty
collection, single-page, exact-limit).
"""
from __future__ import annotations

import json

import pytest
from willow_mcp.db import Store, encode_cursor, decode_cursor


@pytest.fixture
def store(tmp_path):
    return Store(store_root=str(tmp_path))


# ── all_paginated ──────────────────────────────────────────────────────────


class TestAllPaginated:
    def test_empty_collection(self, store):
        items, cursor = store.all_paginated("empty_col")
        assert items == []
        assert cursor is None

    def test_single_page(self, store):
        for i in range(3):
            store.put("ap_single", {"val": i})
        items, cursor = store.all_paginated("ap_single", limit=10)
        assert len(items) == 3
        assert cursor is None

    def test_exact_limit_no_extra_page(self, store):
        for i in range(3):
            store.put("ap_exact", {"val": i})
        items, cursor = store.all_paginated("ap_exact", limit=3)
        assert len(items) == 3
        assert cursor is None

    def test_multi_page_traversal(self, store):
        for i in range(5):
            store.put("ap_multi", {"val": i})
        page1, c1 = store.all_paginated("ap_multi", limit=2)
        assert len(page1) == 2
        assert c1 is not None

        page2, c2 = store.all_paginated("ap_multi", limit=2, cursor=c1)
        assert len(page2) == 2
        assert c2 is not None

        page3, c3 = store.all_paginated("ap_multi", limit=2, cursor=c2)
        assert len(page3) == 1
        assert c3 is None

        all_vals = [r["val"] for r in page1 + page2 + page3]
        assert all_vals == [0, 1, 2, 3, 4]

    def test_created_at_asc_order(self, store):
        store.put("ap_order", {"label": "first"})
        store.put("ap_order", {"label": "second"})
        store.put("ap_order", {"label": "third"})
        items, _ = store.all_paginated("ap_order")
        labels = [r["label"] for r in items]
        assert labels == ["first", "second", "third"]

    def test_metadata_fields_present(self, store):
        store.put("ap_meta", {"x": 1})
        items, _ = store.all_paginated("ap_meta")
        rec = items[0]
        assert "_id" in rec
        assert "_created" in rec
        assert "_updated" in rec
        assert "_deviation" in rec
        assert "_action" in rec


# ── query_paginated ────────────────────────────────────────────────────────


class TestQueryPaginated:
    def test_empty_collection(self, store):
        items, cursor = store.query_paginated("qp_empty")
        assert items == []
        assert cursor is None

    def test_no_filters_default_sort(self, store):
        store.put("qp_default", {"v": "a"})
        store.put("qp_default", {"v": "b"})
        items, _ = store.query_paginated("qp_default")
        assert [r["v"] for r in items] == ["a", "b"]

    def test_equality_filter(self, store):
        store.put("qp_filter", {"status": "open", "val": 1})
        store.put("qp_filter", {"status": "closed", "val": 2})
        store.put("qp_filter", {"status": "open", "val": 3})

        items, _ = store.query_paginated(
            "qp_filter", filters={"status": "open"})
        assert len(items) == 2
        assert all(r["status"] == "open" for r in items)

    def test_multiple_filters(self, store):
        store.put("qp_mfilt", {"status": "open", "topic": "a", "v": 1})
        store.put("qp_mfilt", {"status": "open", "topic": "b", "v": 2})
        store.put("qp_mfilt", {"status": "closed", "topic": "a", "v": 3})

        items, _ = store.query_paginated(
            "qp_mfilt", filters={"status": "open", "topic": "a"})
        assert len(items) == 1
        assert items[0]["v"] == 1

    def test_sort_desc(self, store):
        store.put("qp_desc", {"priority": 1, "label": "low"})
        store.put("qp_desc", {"priority": 3, "label": "high"})
        store.put("qp_desc", {"priority": 2, "label": "mid"})

        items, _ = store.query_paginated(
            "qp_desc",
            sort=[("priority", "DESC"), ("_id", "ASC")],
        )
        assert [r["label"] for r in items] == ["high", "mid", "low"]

    def test_sort_asc(self, store):
        store.put("qp_asc", {"priority": 3})
        store.put("qp_asc", {"priority": 1})
        store.put("qp_asc", {"priority": 2})

        items, _ = store.query_paginated(
            "qp_asc",
            sort=[("priority", "ASC"), ("_id", "ASC")],
        )
        assert [r["priority"] for r in items] == [1, 2, 3]

    def test_keyset_cursor_multi_page(self, store):
        for i in range(7):
            store.put("qp_page", {"idx": i})

        all_items = []
        cursor = None
        while True:
            items, cursor = store.query_paginated(
                "qp_page", limit=3, cursor=cursor)
            all_items.extend(items)
            if cursor is None:
                break

        assert len(all_items) == 7
        assert [r["idx"] for r in all_items] == list(range(7))

    def test_cursor_with_desc_sort(self, store):
        for i in range(5):
            store.put("qp_cdesc", {"score": i * 10})

        page1, c1 = store.query_paginated(
            "qp_cdesc",
            sort=[("score", "DESC"), ("_id", "ASC")],
            limit=2,
        )
        assert [r["score"] for r in page1] == [40, 30]
        assert c1 is not None

        page2, c2 = store.query_paginated(
            "qp_cdesc",
            sort=[("score", "DESC"), ("_id", "ASC")],
            limit=2,
            cursor=c1,
        )
        assert [r["score"] for r in page2] == [20, 10]
        assert c2 is not None

        page3, c3 = store.query_paginated(
            "qp_cdesc",
            sort=[("score", "DESC"), ("_id", "ASC")],
            limit=2,
            cursor=c2,
        )
        assert [r["score"] for r in page3] == [0]
        assert c3 is None

    def test_filter_plus_cursor(self, store):
        for i in range(6):
            store.put("qp_fc", {"status": "open" if i % 2 == 0 else "closed",
                                "idx": i})

        all_open = []
        cursor = None
        while True:
            items, cursor = store.query_paginated(
                "qp_fc", filters={"status": "open"}, limit=1, cursor=cursor)
            all_open.extend(items)
            if cursor is None:
                break

        assert len(all_open) == 3
        assert all(r["status"] == "open" for r in all_open)

    def test_limit_one(self, store):
        store.put("qp_one", {"v": "a"})
        store.put("qp_one", {"v": "b"})
        items, cursor = store.query_paginated("qp_one", limit=1)
        assert len(items) == 1
        assert cursor is not None

    def test_exact_limit_no_spurious_cursor(self, store):
        for i in range(3):
            store.put("qp_exact", {"v": i})
        items, cursor = store.query_paginated("qp_exact", limit=3)
        assert len(items) == 3
        assert cursor is None

    def test_sort_by_meta_fields(self, store):
        store.put("qp_meta", {"v": "a"})
        store.put("qp_meta", {"v": "b"})
        items, _ = store.query_paginated(
            "qp_meta", sort=[("_created", "DESC"), ("_id", "ASC")])
        assert items[0]["v"] == "b"
        assert items[1]["v"] == "a"


# ── _json_col_expr ─────────────────────────────────────────────────────────


class TestJsonColExpr:
    def test_id_mapping(self, store):
        assert store._json_col_expr("_id") == "id"

    def test_created_mapping(self, store):
        assert store._json_col_expr("_created") == "created_at"

    def test_updated_mapping(self, store):
        assert store._json_col_expr("_updated") == "updated_at"

    def test_json_field(self, store):
        assert store._json_col_expr("status") == "json_extract(data, '$.status')"

    def test_rejects_invalid_field(self, store):
        with pytest.raises(ValueError, match="invalid field name"):
            store._json_col_expr("Robert'; DROP TABLE records;--")


# ── Cursor round-trip ──────────────────────────────────────────────────────


class TestCursorEncoding:
    def test_string_round_trip(self):
        original = "2026-08-19T12:00:00"
        assert decode_cursor(encode_cursor(original)) == original

    def test_json_array_round_trip(self):
        vals = [42, "abc"]
        encoded = encode_cursor(json.dumps(vals))
        decoded = json.loads(decode_cursor(encoded))
        assert decoded == vals

    def test_int_types_preserved(self):
        vals = [3, "id-abc"]
        encoded = encode_cursor(json.dumps(vals))
        decoded = json.loads(decode_cursor(encoded))
        assert isinstance(decoded[0], int)
        assert isinstance(decoded[1], str)
