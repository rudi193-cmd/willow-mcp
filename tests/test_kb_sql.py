"""Tests for _kb_sql.py — shared KB SQL helpers (build_select, row_to_dict)."""
from __future__ import annotations

from willow_mcp._kb_sql import KNOWLEDGE_FIELDS, build_select, row_to_dict


class TestKnowledgeFields:
    def test_expected_fields(self):
        assert KNOWLEDGE_FIELDS == ["id", "content", "domain", "source", "tags"]


class TestBuildSelect:
    def _mapping(self, overrides=None):
        base = {
            "id": {"column": "atom_id"},
            "content": {"column": "body"},
            "domain": {"column": "domain"},
            "source": {"column": "src"},
            "tags": {"column": "tags"},
        }
        if overrides:
            base.update(overrides)
        return base

    def test_all_present(self):
        clause, present, unmapped = build_select(
            KNOWLEDGE_FIELDS, self._mapping())
        assert present == ["id", "content", "domain", "source", "tags"]
        assert unmapped == []
        assert '"atom_id" AS "id"' in clause
        assert '"body" AS "content"' in clause

    def test_unmapped_field(self):
        mapping = self._mapping({"tags": {"column": None}})
        clause, present, unmapped = build_select(KNOWLEDGE_FIELDS, mapping)
        assert "tags" in unmapped
        assert "tags" not in present
        assert '"tags"' not in clause

    def test_multiple_unmapped(self):
        mapping = self._mapping({
            "tags": {"column": None},
            "source": {"column": None},
        })
        _, present, unmapped = build_select(KNOWLEDGE_FIELDS, mapping)
        assert set(unmapped) == {"tags", "source"}
        assert "tags" not in present
        assert "source" not in present

    def test_empty_fields_wanted(self):
        clause, present, unmapped = build_select([], self._mapping())
        assert clause == ""
        assert present == []
        assert unmapped == []

    def test_select_clause_format(self):
        mapping = self._mapping()
        clause, _, _ = build_select(["id", "content"], mapping)
        parts = [p.strip() for p in clause.split(",")]
        assert parts == ['"atom_id" AS "id"', '"body" AS "content"']


class TestRowToDict:
    def test_basic_mapping(self):
        row = ("abc-123", "some content", "engineering")
        present = ["id", "content", "domain"]
        result = row_to_dict(row, present, [])
        assert result == {"id": "abc-123", "content": "some content",
                          "domain": "engineering"}

    def test_unmapped_filled_with_none(self):
        row = ("abc-123",)
        present = ["id"]
        result = row_to_dict(row, present, ["tags", "source"])
        assert result == {"id": "abc-123", "tags": None, "source": None}

    def test_empty_row(self):
        result = row_to_dict((), [], ["id", "content"])
        assert result == {"id": None, "content": None}
