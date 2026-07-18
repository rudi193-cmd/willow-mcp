"""Lineage — the story of *this* willow, as queryable atoms and edges.

Agents dropped into a running willow keep asking the same class of question:
"where did this come from, what was here before, why is it this way." A plain
knowledge record answers "what is true"; a lineage atom answers **provenance** —
origin, rationale, and the typed relationships to what came before.

The MECHANISM is portable (every willow instance fills it with its OWN story);
the CONTENT is not (willow's specific history, if it ships at all, is a separate
seed/lore pack kept out of the agent-neutral base).

Two layers, split deliberately after seeing willow's own 647k-edge
`knowledge_edges` graph (which is a `{from, to, relation, context}` triple store
with an open relation vocabulary — `explains`, `precedes`, `implements`,
`depends_on`, …):

  * NODES — the disciplined part `knowledge_edges` does NOT provide: an atom with
    rationale, evidence, authority, and the cite-or-refuse rule. Stored in the
    `lineage` collection, keyed by a stable slug id.
  * EDGES — the SAME shape willow already proved, but in our OWN `lineage_edges`
    collection (not the vault's, so the base stays portable and we never write
    into inherited personal data). A relationship is a row
    `{from, to, relation, context}`; DIRECTION IS QUERIED, never stored twice —
    "is X current?" is "does any edge point `to: X` with `relation: supersedes`?",
    which cannot drift the way a hand-kept `superseded_by` array can.

Three relations are traversed by `why`, each earning its place because it makes
`why` render differently AND an agent act differently:

    supersedes     B replaces A  → an agent must NOT follow the superseded atom
    derived_from   B came from A, both still valid → answers "where from" WITHOUT
                   falsely retiring A (the distinction a single `supersedes` edge
                   would collapse — and did, in the first prototype)
    motivated_by   B exists because of some friction/decision (may point at a gap
                   id, another atom, or an external node) → answers "why now"

The relation vocabulary is open (edges may carry any relation), but these three
are what the provenance verbs read.

Discipline that keeps this from rotting into self-congratulatory lore: an atom
must answer a question an agent will actually ask (a non-empty `rationale`) AND
cite something (at least one `evidence` item). An atom that can't cite is a
story, not memory — `record` refuses it.
"""
from __future__ import annotations

from typing import Optional

NODES = "lineage"
EDGES = "lineage_edges"

SUPERSEDES = "supersedes"
DERIVED_FROM = "derived_from"
MOTIVATED_BY = "motivated_by"
_TRAVERSED = (SUPERSEDES, DERIVED_FROM, MOTIVATED_BY)


class Lineage:
    """Provenance as nodes (`lineage`) plus typed directional edges
    (`lineage_edges`). The atom's slug is its Store record id, so an edge's
    `from`/`to` are just those slugs (or any external node id — the edge store
    enforces no referential integrity, exactly like willow's own edge graph)."""

    def __init__(self, store, nodes: str = NODES, edges: str = EDGES):
        self.store = store
        self.collection = nodes      # node collection (kept name `collection`
        self.edges = edges           # for the server's collection_permitted check)

    # ── edge primitives ──────────────────────────────────────────────────────
    def _edge_id(self, frm: str, relation: str, to: str) -> str:
        # composite id → re-recording the same edge is idempotent (no dupes)
        return f"{frm}::{relation}::{to}"

    def _put_edge(self, frm: str, to: str, relation: str, context: str = "") -> None:
        self.store.put(self.edges,
                       {"from": frm, "to": to, "relation": relation, "context": context or ""},
                       record_id=self._edge_id(frm, relation, to))

    def _all_edges(self) -> list:
        # The lineage edge set is this willow's OWN provenance — small (not the
        # vault's 647k). A full read is fine at this scale; if it ever grows,
        # this is the one place to add a from/to index.
        return self.store.all(self.edges)

    # ── write ────────────────────────────────────────────────────────────────
    def record(self, id: str, title: str, rationale: str, origin: str = "",
               authority: str = "", evidence: Optional[list] = None,
               tags: Optional[list] = None, supersedes: Optional[list] = None,
               derived_from: Optional[list] = None, motivated_by: Optional[list] = None,
               edge_context: str = "") -> dict:
        evidence = list(evidence or [])
        if not id or not id.strip():
            return {"error": "id_required", "detail": "a lineage atom needs a stable slug id"}
        if not rationale or not rationale.strip():
            return {"error": "rationale_required",
                    "detail": "a lineage atom must say WHY — that is the load-bearing field"}
        if not evidence:
            return {"error": "evidence_required",
                    "detail": "cite at least one source (PR / commit / file / session) — "
                              "an atom that can't cite is lore, not memory"}

        # The node carries NO edge arrays — relationships live in `lineage_edges`.
        node = {"id": id, "title": title or id, "rationale": rationale.strip(),
                "origin": origin, "authority": authority,
                "evidence": evidence, "tags": list(tags or [])}
        self.store.put(self.collection, node, record_id=id)

        written = []
        for relation, targets in ((SUPERSEDES, supersedes),
                                  (DERIVED_FROM, derived_from),
                                  (MOTIVATED_BY, motivated_by)):
            for t in (targets or []):
                if not t:
                    continue
                self._put_edge(id, t, relation, edge_context)
                written.append({"relation": relation, "to": t})
        out = {"id": id, "recorded": True}
        if written:
            out["edges"] = written
        return out

    def link(self, frm: str, to: str, relation: str, context: str = "") -> dict:
        """Add a single edge without (re)writing a node — e.g. mark an atom
        `motivated_by` a gap discovered after the fact. Relation is free-form; the
        provenance verbs read supersedes / derived_from / motivated_by."""
        if not frm or not to or not relation:
            return {"error": "from_to_relation_required"}
        self._put_edge(frm, to, relation, context)
        return {"linked": {"from": frm, "to": to, "relation": relation}}

    # ── query ────────────────────────────────────────────────────────────────
    def _resolve(self, query: str, superseded: Optional[set] = None) -> Optional[dict]:
        """Exact slug wins; else full-text search the node collection, preferring
        a CURRENT atom (nothing supersedes it) over an archived one."""
        atom = self.store.get(self.collection, query)
        if atom is not None:
            return atom
        hits = self.store.search(self.collection, query)
        if not hits:
            return None
        superseded = superseded if superseded is not None else self._superseded_set()
        hits.sort(key=lambda a: (a.get("_id") in superseded, a.get("_id", "")))
        return hits[0]

    def _superseded_set(self, edges: Optional[list] = None) -> set:
        edges = edges if edges is not None else self._all_edges()
        return {e["to"] for e in edges if e.get("relation") == SUPERSEDES and e.get("to")}

    def _node_summary(self, node_id: str) -> dict:
        n = self.store.get(self.collection, node_id)
        if n is None:
            return {"id": node_id, "title": "(not a recorded atom)", "external": True}
        return {"id": node_id, "title": n.get("title", ""), "rationale": n.get("rationale", "")}

    def _walk_supersedes(self, start: str, edges: list) -> list:
        """Outgoing `supersedes` edges, transitively → the decision history
        (what this atom replaced, and what THAT replaced). Cycle-guarded."""
        chain, seen = [], set()
        frontier = [e["to"] for e in edges if e.get("from") == start and e.get("relation") == SUPERSEDES]
        while frontier:
            nid = frontier.pop(0)
            if nid in seen:
                continue
            seen.add(nid)
            chain.append(self._node_summary(nid))
            frontier.extend(e["to"] for e in edges
                            if e.get("from") == nid and e.get("relation") == SUPERSEDES)
        return chain

    def why(self, query: str) -> dict:
        q = (query or "").strip()
        if not q:
            return {"error": "query_required"}
        edges = self._all_edges()
        superseded = self._superseded_set(edges)
        atom = self._resolve(q, superseded)
        if atom is None:
            return {"query": q, "matched": None,
                    "answer": f"no lineage atom found for {q!r} — nothing recorded its provenance yet"}
        # A search hit lacks the _created meta that get() injects; re-fetch by id
        # so `recorded_at` is consistent however the atom was matched.
        atom = self.store.get(self.collection, atom["_id"]) or atom
        aid = atom["_id"]

        out_edges = [e for e in edges if e.get("from") == aid]
        superseded_by = [e["from"] for e in edges
                         if e.get("to") == aid and e.get("relation") == SUPERSEDES]
        chain = self._walk_supersedes(aid, edges)
        derived_from = [self._node_summary(e["to"]) for e in out_edges
                        if e.get("relation") == DERIVED_FROM]
        motivated_by = [e["to"] for e in out_edges if e.get("relation") == MOTIVATED_BY]
        is_current = not superseded_by
        return {
            "query": q,
            "matched": aid,
            "atom": {
                "id": atom.get("id"), "title": atom.get("title"),
                "rationale": atom.get("rationale"), "origin": atom.get("origin"),
                "authority": atom.get("authority"), "evidence": atom.get("evidence", []),
                "tags": atom.get("tags", []), "recorded_at": atom.get("_created"),
                "is_current": is_current,
            },
            "supersedes_chain": chain,
            "superseded_by": superseded_by,
            "derived_from": derived_from,
            "motivated_by": motivated_by,
            "answer": self._synthesize(atom, chain, superseded_by, derived_from, motivated_by),
        }

    @staticmethod
    def _synthesize(atom: dict, chain: list, superseded_by: list,
                    derived_from: list, motivated_by: list) -> str:
        title = atom.get("title") or atom.get("id")
        parts = [f"{title} exists because {atom.get('rationale')}"]
        if atom.get("origin"):
            parts.append(f"It came from {atom['origin']}")
        if derived_from:
            parts.append("Derived from: " + "; ".join(d["id"] for d in derived_from))
        if motivated_by:
            parts.append("Motivated by: " + "; ".join(motivated_by))
        if chain:
            parts.append("It replaced: " + "; ".join(c["id"] for c in chain))
        if superseded_by:
            parts.append("NOTE: no longer current — superseded by " + ", ".join(superseded_by))
        else:
            parts.append("This is the current state")
        ev = atom.get("evidence") or []
        if ev:
            parts.append("Evidence: " + ", ".join(str(e) for e in ev))
        return ". ".join(parts) + "."

    # ── list ───────────────────────────────────────────────────────────────────
    def list_atoms(self, current_only: bool = False) -> list:
        superseded = self._superseded_set()
        out = []
        for a in self.store.all(self.collection):
            aid = a.get("id")
            if current_only and aid in superseded:
                continue
            out.append({"id": aid, "title": a.get("title"),
                        "is_current": aid not in superseded, "tags": a.get("tags", [])})
        out.sort(key=lambda r: r["id"])
        return out
