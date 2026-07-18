"""Tests for the lineage / provenance layer — the "story of this willow".

Nodes live in `lineage` (disciplined atoms); relationships are typed edges in
`lineage_edges` ({from,to,relation,context}); direction is queried, never stored
twice. The load-bearing correctness case: `derived_from` must NOT retire its
ancestor — the distinction the first single-`supersedes`-edge prototype collapsed.
"""

import pytest

from willow_mcp.db import Store
from willow_mcp.lineage import Lineage, EDGES, SUPERSEDES


@pytest.fixture
def lin(tmp_path):
    return Lineage(Store(store_root=str(tmp_path)))


def _seed_supersession(lin):
    lin.record(id="old", title="the old way", rationale="it was the first cut",
               evidence=["commit aaa"])
    lin.record(id="new", title="the new way", rationale="agents needed more",
               origin="a build session", supersedes=["old"], evidence=["PR #2"])


# ── discipline: no lore ───────────────────────────────────────────────────────

def test_rationale_required(lin):
    assert lin.record(id="x", title="t", rationale="  ", evidence=["c"])["error"] == "rationale_required"


def test_evidence_required(lin):
    assert lin.record(id="x", title="t", rationale="because")["error"] == "evidence_required"


def test_id_required(lin):
    assert lin.record(id="", title="t", rationale="why", evidence=["c"])["error"] == "id_required"


def test_valid_atom_records_with_no_edges(lin):
    r = lin.record(id="a", title="A", rationale="why A", evidence=["file.py"])
    assert r == {"id": "a", "recorded": True}          # no edges key when none


# ── node/edge separation ──────────────────────────────────────────────────────

def test_node_carries_no_edge_arrays(lin):
    _seed_supersession(lin)
    node = lin.store.get("lineage", "new")
    assert "supersedes" not in node and "superseded_by" not in node
    # the relationship is a row in the edge collection instead
    edges = lin.store.all(EDGES)
    assert any(e["from"] == "new" and e["to"] == "old" and e["relation"] == SUPERSEDES
               for e in edges)


def test_record_reports_edges_written(lin):
    lin.record(id="old", title="o", rationale="r", evidence=["c"])
    r = lin.record(id="new", title="n", rationale="r", evidence=["c"],
                   supersedes=["old"], derived_from=["src"], motivated_by=["gap:7"])
    rels = {(e["relation"], e["to"]) for e in r["edges"]}
    assert rels == {("supersedes", "old"), ("derived_from", "src"), ("motivated_by", "gap:7")}


# ── supersession (direction is queried) ───────────────────────────────────────

def test_supersession_current_status_from_edges(lin):
    _seed_supersession(lin)
    assert lin.why("old")["atom"]["is_current"] is False
    assert lin.why("old")["superseded_by"] == ["new"]
    assert lin.why("new")["atom"]["is_current"] is True
    assert [c["id"] for c in lin.why("new")["supersedes_chain"]] == ["old"]


def test_transitive_supersession_chain(lin):
    lin.record(id="v1", title="v1", rationale="r", evidence=["c"])
    lin.record(id="v2", title="v2", rationale="r", evidence=["c"], supersedes=["v1"])
    lin.record(id="v3", title="v3", rationale="r", evidence=["c"], supersedes=["v2"])
    chain = [c["id"] for c in lin.why("v3")["supersedes_chain"]]
    assert chain == ["v2", "v1"]


def test_rerecord_node_preserves_edges(lin):
    _seed_supersession(lin)
    lin.record(id="old", title="the old way (clarified)",
               rationale="first cut, jsonl only", evidence=["commit aaa"])
    # edges live in their own collection, untouched by the node rewrite
    assert lin.why("old")["superseded_by"] == ["new"]


# ── derived_from does NOT retire its ancestor (the key correctness case) ───────

def test_derived_from_keeps_ancestor_current(lin):
    lin.record(id="file-reader", title="file adapter", rationale="jsonl first",
               evidence=["claude_code.py"])
    lin.record(id="db-reader", title="db adapters",
               rationale="agents needed db corpora too",
               derived_from=["file-reader"], evidence=["PR #2"])
    # the derivation is recorded...
    df = lin.why("db-reader")["derived_from"]
    assert [d["id"] for d in df] == ["file-reader"]
    # ...but the ancestor is STILL CURRENT — derivation is not replacement
    assert lin.why("file-reader")["atom"]["is_current"] is True
    assert lin.why("file-reader")["superseded_by"] == []


def test_motivated_by_may_point_at_external_node(lin):
    lin.record(id="lineage-tools", title="lineage tools",
               rationale="agents kept asking about provenance",
               motivated_by=["gap:provenance-asks"], evidence=["lineage.py"])
    mb = lin.why("lineage-tools")["motivated_by"]
    assert mb == ["gap:provenance-asks"]              # external id, need not exist


# ── link (post-hoc edge) ──────────────────────────────────────────────────────

def test_link_adds_edge_without_a_node(lin):
    lin.record(id="a", title="A", rationale="r", evidence=["c"])
    lin.record(id="b", title="B", rationale="r", evidence=["c"])
    lin.link("b", "a", SUPERSEDES)
    assert lin.why("a")["superseded_by"] == ["b"]


def test_link_requires_all_three(lin):
    assert lin.link("", "a", "supersedes")["error"] == "from_to_relation_required"


def test_edge_is_idempotent(lin):
    lin.record(id="a", title="A", rationale="r", evidence=["c"])
    lin.record(id="b", title="B", rationale="r", evidence=["c"])
    lin.link("b", "a", SUPERSEDES)
    lin.link("b", "a", SUPERSEDES)                     # same edge twice
    assert sum(1 for e in lin.store.all(EDGES)
               if e["from"] == "b" and e["to"] == "a") == 1


# ── the why verb ──────────────────────────────────────────────────────────────

def test_why_exact_slug_and_meta(lin):
    _seed_supersession(lin)
    r = lin.why("new")
    assert r["matched"] == "new"
    assert "agents needed more" in r["answer"]
    assert r["atom"]["recorded_at"] is not None


def test_why_free_text_prefers_current(lin):
    _seed_supersession(lin)                            # both mention "way"
    assert lin.why("way")["matched"] == "new"


def test_why_free_text_has_consistent_meta(lin):
    _seed_supersession(lin)
    assert lin.why("first cut")["atom"]["recorded_at"] is not None


def test_why_miss_is_honest(lin):
    r = lin.why("nope")
    assert r["matched"] is None and "no lineage atom found" in r["answer"]


def test_why_empty_query(lin):
    assert lin.why("  ")["error"] == "query_required"


# ── tag siblings (sideways provenance) ────────────────────────────────────────

def test_why_surfaces_tag_siblings_sorted_by_overlap(lin):
    lin.record(id="a", title="A", rationale="r", evidence=["c"], tags=["adapters", "sqlite"])
    lin.record(id="b", title="B", rationale="r", evidence=["c"], tags=["adapters", "sqlite"])
    lin.record(id="c", title="C", rationale="r", evidence=["c"], tags=["adapters"])
    lin.record(id="z", title="Z", rationale="r", evidence=["c"], tags=["unrelated"])
    sibs = lin.why("a")["related_by_tag"]
    ids = [s["id"] for s in sibs]
    assert "z" not in ids and "a" not in ids            # unrelated + self excluded
    assert ids == ["b", "c"]                            # b shares 2 tags, c shares 1
    assert sibs[0]["shared_tags"] == ["adapters", "sqlite"]


def test_tag_siblings_mark_current_status(lin):
    lin.record(id="old", title="old", rationale="r", evidence=["c"], tags=["area"])
    lin.record(id="new", title="new", rationale="r", evidence=["c"], tags=["area"],
               supersedes=["old"])
    # querying a third atom in the area sees old as archived, new as live
    lin.record(id="probe", title="p", rationale="r", evidence=["c"], tags=["area"])
    by_id = {s["id"]: s for s in lin.why("probe")["related_by_tag"]}
    assert by_id["old"]["is_current"] is False
    assert by_id["new"]["is_current"] is True


def test_no_tags_no_siblings(lin):
    lin.record(id="a", title="A", rationale="r", evidence=["c"])
    assert lin.why("a")["related_by_tag"] == []


# ── list ──────────────────────────────────────────────────────────────────────

def test_list_current_only_hides_superseded(lin):
    _seed_supersession(lin)
    assert {a["id"] for a in lin.list_atoms()} == {"old", "new"}
    assert {a["id"] for a in lin.list_atoms(current_only=True)} == {"new"}
