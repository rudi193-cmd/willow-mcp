"""Shared helpers for KB (knowledge-base) SQL queries.

Factored out of server.py so resources.py can use the same definitions
without a circular import (server.py imports resources.py at module level).
"""
from __future__ import annotations

KNOWLEDGE_FIELDS = ["id", "content", "domain", "source", "tags"]


def build_select(
    fields_wanted: list[str], mapping_fields: dict
) -> tuple[str, list[str], list[str]]:
    """From a resolved mapping, build a SELECT column list using only real,
    confirmed-present columns.  Returns (select_clause, present_fields,
    unmapped_fields) — present_fields is the row-tuple order to zip results
    against; unmapped_fields is surfaced to the caller, never silently
    dropped."""
    parts, present, unmapped = [], [], []
    for field in fields_wanted:
        col = mapping_fields[field]["column"]
        if col is None:
            unmapped.append(field)
            continue
        parts.append(f'"{col}" AS "{field}"')
        present.append(field)
    return ", ".join(parts), present, unmapped


def row_to_dict(
    row: tuple, present_fields: list[str], unmapped_fields: list[str]
) -> dict:
    """Convert a DB row into a dict using the schema-profile field names."""
    rec = dict(zip(present_fields, row))
    for field in unmapped_fields:
        rec[field] = None
    return rec
