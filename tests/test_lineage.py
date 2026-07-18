"""Tests for the lineage / provenance layer — the "story of this willow" atoms."""

import pytest

from willow_mcp.db import Store
from willow_mcp.lineage import Lineage


@pytest.fixture
def lin(tmp_path):
    return Lineage(Store(store_root=str(tmp_path)))


def _seed_pair(lin):
    """An older atom and the atom that supersedes it."""
    lin.record(id="old", title="the old way", rationale="it was the first cut",
               evidence=["commit aaa"])
    lin.record(id="new", title="the new way", rationale="agents needed more",
               origin="a build session", supersedes=["old"], evidence=["PR #2"])


# ── discipline: no lore ───────────────────────────────────────────────────────

def test_rationale_is_required(lin):
    r = lin.record(id="x", title="t", rationale="  ", evidence=["c"])
    assert r["error"] == "rationale_required"


def test_evidence_is_required(lin):
    r = lin.record(id="x", title="t", rationale="because")
    assert r["error"] == "evidence_required"


def test_id_is_required(lin):
    r = lin.record(id="", title="t", rationale="because", evidence=["c"])
    assert r["error"] == "id_required"


def test_valid_atom_records(lin):
    r = lin.record(id="a", title="A", rationale="why A", evidence=["file.py"])
    assert r == {"id": "a", "recorded": True}


# ── supersession graph ────────────────────────────────────────────────────────

def test_supersedes_patches_predecessor_both_directions(lin):
    _seed_pair(lin)
    old = lin.why("old")
    new = lin.why("new")
    assert old["atom"]["is_current"] is False
    assert old["superseded_by"] == ["new"]
    assert new["atom"]["is_current"] is True
    assert [c["id"] for c in new["supersedes_chain"]] == ["old"]


def test_record_reports_unknown_predecessor_not_hidden(lin):
    r = lin.record(id="b", title="B", rationale="why", evidence=["c"],
                   supersedes=["does-not-exist"])
    assert r["supersedes_unknown"] == ["does-not-exist"]


def test_rerecord_preserves_superseded_by(lin):
    _seed_pair(lin)
    # correct 'old' in place; its superseded_by pointer must survive the rewrite
    lin.record(id="old", title="the old way (clarified)",
               rationale="it was the first cut, jsonl only", evidence=["commit aaa"])
    assert lin.why("old")["superseded_by"] == ["new"]


# ── the why verb ──────────────────────────────────────────────────────────────

def test_why_exact_slug(lin):
    _seed_pair(lin)
    r = lin.why("new")
    assert r["matched"] == "new"
    assert "agents needed more" in r["answer"]
    assert r["atom"]["recorded_at"] is not None      # normalized meta


def test_why_free_text_prefers_current_head(lin):
    # both atoms mention "way"; the current one should win
    _seed_pair(lin)
    r = lin.why("way")
    assert r["matched"] == "new"
    assert r["atom"]["is_current"] is True


def test_why_free_text_has_consistent_meta(lin):
    _seed_pair(lin)
    # a search-matched atom must still carry recorded_at (get()-normalized)
    assert lin.why("first cut")["atom"]["recorded_at"] is not None


def test_why_miss_is_honest(lin):
    r = lin.why("nothing-here")
    assert r["matched"] is None
    assert "no lineage atom found" in r["answer"]


def test_why_empty_query(lin):
    assert lin.why("   ")["error"] == "query_required"


# ── list ──────────────────────────────────────────────────────────────────────

def test_list_current_only_hides_superseded(lin):
    _seed_pair(lin)
    all_ids = {a["id"] for a in lin.list_atoms()}
    current_ids = {a["id"] for a in lin.list_atoms(current_only=True)}
    assert all_ids == {"old", "new"}
    assert current_ids == {"new"}
