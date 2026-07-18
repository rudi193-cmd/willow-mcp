"""
commitment_ledger.py — Willow Commitment Membrane core (Jarvis layer 2, Step 1 skeleton).

The OUTWARD mirror of the voice ingress membrane. Where the ear kept the fleet's boundary
against the world's audio, this keeps the operator's record of their own commitments —
Tally's half of the governance seat (KB 0E8C90C0), the same tamper-evident discipline
turned to face the human instead of the fleet.

Three disciplines, each the outward image of one the fleet already runs:
  1. RECEIPT-NOT-RECORDING — store the commitment FACT (title / when / who), never the
     sensitive event body/notes/location. Mirror of the voice membrane's receipts.
  2. STATES-NOT-DELETIONS — a cancelled event is a WITHDRAWN state, a moved event keeps its
     old time in history. Nothing is deleted. Mirror of FRANK / the envelope registry.
  3. NO NEW AUTHORITY — the ledger never writes the calendar. A proposed mutation ("cancel
     my 3pm") routes through the existing SAFE gate; a spoken or typed request hits the same
     stop. The membrane is read-in; action is gated-out.

And it obeys the DEW RULE: dew_surface() is silent by default. It speaks only when the
halves disagree — a commitment imminent, two commitments in conflict, or a change the
operator has not yet acknowledged (the split-stick mismatch). A surface that speaks whenever
it can is another chatty assistant; this one is confident enough to say nothing.

Imperative-shell pattern (as with the voice controller): the real caldav/gcal client is the
injected `source` driver; all discipline and dew logic live in this deterministic core and
are unit-testable with a stub source and an explicit clock.

Design: willow/design/willow-commitment-membrane.md · pure script, no models, no network. ΔΣ=42
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Callable, Optional, Protocol, runtime_checkable


class CommitmentState(Enum):
    ACTIVE = auto()      # a live commitment (a move keeps it ACTIVE at a new time)
    WITHDRAWN = auto()   # cancelled — the record and its history are KEPT, never deleted


@dataclass(frozen=True)
class CalendarEvent:
    """Raw event from an injected source.

    `body` is the SENSITIVE content (description / notes / location) the membrane must not
    let cross into fleet memory verbatim. The ledger reads it to derive the fact, then drops
    it — it is never stored on a Commitment.
    """
    uid: str
    title: str
    start: datetime
    end: Optional[datetime] = None
    attendees: tuple[str, ...] = ()
    body: str = ""
    cancelled: bool = False


# Fields that would turn a stored commitment / receipt into a recording of sensitive detail.
_FORBIDDEN_FACT_KEYS = frozenset({"body", "notes", "description", "location", "raw"})


@dataclass
class StateChange:
    """One appended history entry. Records the fact of a transition, never event content."""
    tick: int
    state: CommitmentState
    when: datetime          # the commitment's start AS OF this change (moves are recorded)
    reason: str = ""


@dataclass
class Commitment:
    """The retained FACT of a commitment. Deliberately carries no body/notes/location —
    receipt-not-recording is enforced by the absence of a field to hold them."""
    uid: str
    title: str
    when: datetime
    end: Optional[datetime]
    who: tuple[str, ...]
    state: CommitmentState
    acknowledged: bool
    history: list[StateChange] = field(default_factory=list)


@dataclass
class Surfacing:
    """One thing the dew rule decided is worth the operator's attention. Minimal by design."""
    kind: str                 # "imminent" | "conflict" | "mismatch"
    uids: tuple[str, ...]
    when: datetime
    fact: str                 # title + time only — never the sensitive body


@runtime_checkable
class CalendarSource(Protocol):
    """Read-only ingest contract for a real calendar (caldav / gcal).

    fetch() returns the current events. There is deliberately NO create/update/delete here:
    the membrane ingests read-only, and mutations are proposals routed through the SAFE gate,
    never a direct ledger→calendar write. A real adapter (calendar_source.CalDavSource) fills
    body/attendees from live data; the ledger drops body at ingest regardless.
    """

    def fetch(self) -> list[CalendarEvent]: ...


class StubCalendarSource:
    """Deterministic synthetic source. No write methods — the read-only contract by example."""

    def __init__(self, events: Optional[list[CalendarEvent]] = None):
        self._events = list(events or [])

    def fetch(self) -> list[CalendarEvent]:
        return list(self._events)

    def set_events(self, events: list[CalendarEvent]) -> None:
        self._events = list(events)


class Refused(Exception):
    """Raised by the SAFE gate to refuse a proposed calendar mutation."""


@dataclass
class DewConfig:
    lead: timedelta = timedelta(minutes=15)   # how soon counts as "imminent"


class CommitmentLedger:
    """The deterministic core. Drive it with ingest() and read it with dew_surface(now)."""

    def __init__(
        self,
        *,
        source: CalendarSource,
        config: Optional[DewConfig] = None,
        gate_fn: Optional[Callable[[str, Commitment], bool]] = None,
    ):
        self.source = source
        self.cfg = config or DewConfig()
        # SAFE gate for any proposed mutation. Default DENIES — fail-closed, no new authority.
        self.gate_fn = gate_fn or (lambda action, commitment: False)
        self.commitments: dict[str, Commitment] = {}
        self.receipts: list[dict] = []
        self._tick = 0

    # ---- receipts: the fact, never the content ----
    def _receipt(self, event: str, **meta) -> None:
        leaked = _FORBIDDEN_FACT_KEYS & meta.keys()
        if leaked:
            raise AssertionError(f"receipt {event!r} would leak content via {sorted(leaked)}")
        self.receipts.append({"tick": self._tick, "event": event, **meta})

    # ---- ingest: read-only reconcile of the source against the ledger ----
    def ingest(self) -> None:
        self._tick += 1
        for ev in self.source.fetch():
            self._ingest_one(ev)

    def _ingest_one(self, ev: CalendarEvent) -> None:
        existing = self.commitments.get(ev.uid)
        if existing is None:
            state = CommitmentState.WITHDRAWN if ev.cancelled else CommitmentState.ACTIVE
            # First sight is the baseline — the calendar IS the operator's record, so a
            # freshly-seen live event is acknowledged; a first-seen cancellation is not.
            c = Commitment(
                uid=ev.uid, title=ev.title, when=ev.start, end=ev.end,
                who=tuple(ev.attendees), state=state,
                acknowledged=not ev.cancelled,
            )
            c.history.append(StateChange(self._tick, state, ev.start,
                                         "created" if not ev.cancelled else "first-seen cancelled"))
            self.commitments[ev.uid] = c
            self._receipt("ingest", uid=ev.uid, state=state.name)  # NB: no body
            return
        # cancellation
        if ev.cancelled and existing.state is not CommitmentState.WITHDRAWN:
            existing.state = CommitmentState.WITHDRAWN
            existing.acknowledged = False
            existing.history.append(StateChange(self._tick, CommitmentState.WITHDRAWN,
                                                existing.when, "cancelled"))
            self._receipt("withdraw", uid=ev.uid)
            return
        # reschedule (kept ACTIVE; old time preserved in history)
        if not ev.cancelled and ev.start != existing.when:
            old = existing.when
            existing.when = ev.start
            existing.end = ev.end
            existing.state = CommitmentState.ACTIVE
            existing.acknowledged = False
            existing.history.append(StateChange(self._tick, CommitmentState.ACTIVE, ev.start,
                                                f"moved from {old.isoformat()}"))
            self._receipt("move", uid=ev.uid)
            return
        # unchanged → no-op

    def acknowledge(self, uid: str) -> None:
        """Operator has seen the change — the halves match again. Recorded, not erased."""
        c = self.commitments.get(uid)
        if c is None:
            return
        self._tick += 1
        c.acknowledged = True
        c.history.append(StateChange(self._tick, c.state, c.when, "acknowledged"))
        self._receipt("acknowledge", uid=uid)

    # ---- the dew rule: silence unless the halves disagree ----
    def dew_surface(self, now: datetime) -> list[Surfacing]:
        out: list[Surfacing] = []
        active = [c for c in self.commitments.values() if c.state is CommitmentState.ACTIVE]
        # imminent — an active commitment starting within the lead window
        for c in active:
            if timedelta(0) <= (c.when - now) <= self.cfg.lead:
                out.append(Surfacing("imminent", (c.uid,), c.when, self._fact(c)))
        # conflict — two active commitments whose intervals overlap
        timed = sorted([c for c in active if c.end is not None], key=lambda c: c.when)
        for i in range(len(timed)):
            for j in range(i + 1, len(timed)):
                a, b = timed[i], timed[j]
                if a.when < b.end and b.when < a.end:
                    out.append(Surfacing("conflict", (a.uid, b.uid), max(a.when, b.when),
                                         f"{self._fact(a)} vs {self._fact(b)}"))
        # mismatch — a change the operator has not acknowledged (the split-stick disagrees)
        for c in self.commitments.values():
            if not c.acknowledged:
                out.append(Surfacing("mismatch", (c.uid,), c.when, self._fact(c)))
        return out

    @staticmethod
    def _fact(c: Commitment) -> str:
        return f"{c.title} @ {c.when.isoformat()}"   # title + time; never the body

    # ---- action: gated-out, never a direct write ----
    def propose_action(self, uid: str, action: str) -> bool:
        """Route a proposed mutation through the SAFE gate. The ledger NEVER writes the
        calendar itself — a spoken or typed 'cancel my 3pm' hits this same stop. Even an
        allowed action is executed by the gated source adapter, not here."""
        c = self.commitments.get(uid)
        if c is None:
            return False
        self._tick += 1
        try:
            allowed = bool(self.gate_fn(action, c))
        except Refused:
            allowed = False
        self._receipt("propose_action", uid=uid, action=action, allowed=allowed)
        return allowed
