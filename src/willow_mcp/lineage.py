"""Lineage — the story of *this* willow, as queryable atoms.

Agents dropped into a running willow keep asking the same class of question:
"where did this come from, what was here before, why is it this way." A plain
knowledge record answers "what is true"; a lineage atom answers **provenance** —
origin, rationale, and supersession history — so an agent can act competently
instead of re-deriving intent from scratch.

The MECHANISM is portable (every willow instance fills it with its OWN story);
the CONTENT is not (willow's specific history ships, if at all, as a separate
seed/lore pack, kept out of the agent-neutral base). This module is the
mechanism: a thin lineage graph over one SOIL collection, with two verbs —
`record` (write an atom) and `why` (answer the question, returning the chain,
not a blob).

An atom (stored as the SOIL record `data`, keyed by its own stable slug id):

    id            stable handle, e.g. "corpus-lens-dual-backend"
    title         one line
    rationale     WHY it exists / why this way  ← the load-bearing field
    origin        where it came from (a session, a commit, a prior system)
    authority     who or what decided
    supersedes    [ids] this atom replaces (older decisions)
    superseded_by [ids] that later replaced THIS one (kept current automatically)
    evidence      [citations] — a PR, a commit, a file, a session
    tags          [str]

The one discipline that keeps this from rotting into self-congratulatory lore:
every atom must answer a question an agent will actually ask (a non-empty
`rationale`) AND cite something (at least one `evidence` item). An atom that
can't cite is a story, not memory — `record` refuses it.
"""
from __future__ import annotations

from typing import Optional

COLLECTION = "lineage"


def _strip_meta(record: dict) -> dict:
    """Drop the Store's injected _id/_created/... keys so a re-write persists only
    the atom's own fields (the meta keys are re-injected on the next read)."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


class Lineage:
    """A provenance graph over one SOIL collection. Uses the atom's slug as the
    Store record id, so `supersedes`/`superseded_by` references ARE record ids —
    no second index to keep in sync."""

    def __init__(self, store, collection: str = COLLECTION):
        self.store = store
        self.collection = collection

    # ── write ────────────────────────────────────────────────────────────────
    def record(self, id: str, title: str, rationale: str, origin: str = "",
               authority: str = "", supersedes: Optional[list] = None,
               evidence: Optional[list] = None, tags: Optional[list] = None) -> dict:
        supersedes = list(supersedes or [])
        evidence = list(evidence or [])
        tags = list(tags or [])
        if not id or not id.strip():
            return {"error": "id_required", "detail": "a lineage atom needs a stable slug id"}
        if not rationale or not rationale.strip():
            return {"error": "rationale_required",
                    "detail": "a lineage atom must say WHY — that is the load-bearing field"}
        if not evidence:
            return {"error": "evidence_required",
                    "detail": "cite at least one source (PR / commit / file / session) — "
                              "an atom that can't cite is lore, not memory"}

        atom = {
            "id": id, "title": title or id, "rationale": rationale.strip(),
            "origin": origin, "authority": authority,
            "supersedes": supersedes, "superseded_by": [],
            "evidence": evidence, "tags": tags,
        }
        # Re-recording the same slug corrects in place, but must not drop the
        # supersession pointers later atoms have already added to it.
        existing = self.store.get(self.collection, id)
        if existing:
            atom["superseded_by"] = existing.get("superseded_by", [])
        self.store.put(self.collection, atom, record_id=id)

        # Patch each predecessor so the graph is walkable both directions and a
        # `why` on the old atom knows it is no longer current.
        patched = []
        missing = []
        for pid in supersedes:
            pred = self.store.get(self.collection, pid)
            if pred is None:
                missing.append(pid)
                continue
            sb = set(pred.get("superseded_by", []))
            if id not in sb:
                sb.add(id)
                clean = _strip_meta(pred)
                clean["superseded_by"] = sorted(sb)
                self.store.update(self.collection, pid, clean)
                patched.append(pid)
        out = {"id": id, "recorded": True}
        if patched:
            out["superseded_marked"] = patched
        if missing:
            out["supersedes_unknown"] = missing   # named, not hidden
        return out

    # ── query ────────────────────────────────────────────────────────────────
    def _resolve(self, query: str) -> Optional[dict]:
        """An exact slug wins; otherwise full-text search the collection and
        prefer a CURRENT atom (not yet superseded) over an archived one."""
        atom = self.store.get(self.collection, query)
        if atom is not None:
            return atom
        hits = self.store.search(self.collection, query)
        if not hits:
            return None
        hits.sort(key=lambda a: (bool(a.get("superseded_by")), a.get("_id", "")))
        return hits[0]

    def why(self, query: str) -> dict:
        q = (query or "").strip()
        if not q:
            return {"error": "query_required"}
        atom = self._resolve(q)
        if atom is None:
            return {"query": q, "matched": None,
                    "answer": f"no lineage atom found for {q!r} — nothing recorded its provenance yet"}
        # Normalize: a search hit lacks the Store's _created meta that get() injects,
        # so re-fetch by id and the "recorded_at" is consistent however we matched.
        atom = self.store.get(self.collection, atom["_id"]) or atom

        # Walk `supersedes` backwards for the decision history (older → what it
        # replaced), breadth-first, cycle-guarded.
        chain = []
        seen = set()
        frontier = list(atom.get("supersedes", []))
        while frontier:
            pid = frontier.pop(0)
            if pid in seen:
                continue
            seen.add(pid)
            pred = self.store.get(self.collection, pid)
            if pred is None:
                chain.append({"id": pid, "title": "(unknown)", "rationale": "", "missing": True})
                continue
            chain.append({"id": pid, "title": pred.get("title", ""),
                          "rationale": pred.get("rationale", "")})
            frontier.extend(pred.get("supersedes", []))

        superseded_by = atom.get("superseded_by", [])
        is_current = not superseded_by
        return {
            "query": q,
            "matched": atom["_id"],
            "atom": {
                "id": atom.get("id"), "title": atom.get("title"),
                "rationale": atom.get("rationale"), "origin": atom.get("origin"),
                "authority": atom.get("authority"), "evidence": atom.get("evidence", []),
                "tags": atom.get("tags", []), "recorded_at": atom.get("_created"),
                "is_current": is_current,
            },
            "supersedes_chain": chain,
            "superseded_by": superseded_by,
            "answer": self._synthesize(atom, chain, superseded_by),
        }

    @staticmethod
    def _synthesize(atom: dict, chain: list, superseded_by: list) -> str:
        title = atom.get("title") or atom.get("id")
        parts = [f"{title} exists because {atom.get('rationale')}"]
        if atom.get("origin"):
            parts.append(f"It came from {atom['origin']}")
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
        rows = self.store.all(self.collection)
        out = []
        for a in rows:
            if current_only and a.get("superseded_by"):
                continue
            out.append({"id": a.get("id"), "title": a.get("title"),
                        "is_current": not a.get("superseded_by"),
                        "tags": a.get("tags", [])})
        out.sort(key=lambda r: r["id"])
        return out
