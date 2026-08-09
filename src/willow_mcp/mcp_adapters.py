"""Pure-stdlib classification of a downstream MCP tool's risk shape.

Name/description heuristics only — no state, no network, no imports beyond
`re`. Used to decide whether a federated call is worth routing through the
human-in-the-loop queue (`human_loop.enqueue`) before it runs, and to shape
the confirmation payload if so.

**Advisory only — not a security boundary.** That sentence is load-bearing,
not decoration: `federation_egress.egress_denial` is the security boundary (a
name lookup against a manifest, an operator-ratified server, standing
consent, and a live lease — all checked from disk at call time). This module
only guesses, from a tool's *name*, how alarming it would look to a human
reading a confirmation queue. A downstream server can name a destructive tool
`get_status` and this module will happily call it "read" — the guess can be
wrong in either direction, and nothing here is allowed to gate a call the
four-key check above already permitted.
"""
from __future__ import annotations

import re
from typing import Any, Optional

#: `\b` word boundaries so these fire on both snake_case names ("delete_repo")
#: and natural-language descriptions ("permanently deletes the record") —
#: `\w*` after each stem also catches the plain-English inflections
#: ("deletes", "deleting", "removed") a description is more likely to use than
#: a name is. Text is normalized (underscores -> spaces) before matching so a
#: word embedded mid-identifier ("list_and_delete_stale") still gets a real
#: boundary rather than sitting between two word characters, where `\b` never
#: fires. Ordered read → write → destructive in `classify_tool` below, not
#: here: the first TIER that matches ANY haystack wins, so a name matching
#: both "list" and "delete" is classified by the more consequential word.
#: Stems drop a trailing silent "e" (delet-, remov-, updat-, ...) so `\w*`
#: also covers the "-ing"/"-ed" inflection English spelling produces by
#: dropping that "e" ("deleting", not "deleteing") — matching only the full
#: word would silently miss the participle form a description is more
#: likely to use than an identifier is.
_DESTRUCTIVE_RE = re.compile(
    r"\b(delet|remov|drop|purg|destroy|wip|revok|terminat|kill)\w*",
    re.IGNORECASE,
)
_WRITE_RE = re.compile(
    r"\b(creat|writ|put|updat|set|send|post|patch|insert|"
    r"execut|run|appl|merg|approv|grant|ratif)\w*",
    re.IGNORECASE,
)
_READ_RE = re.compile(
    r"\b(get|list|read|search|find|fetch|show|describ|status|"
    r"check|quer|view)\w*",
    re.IGNORECASE,
)

CLASSIFICATIONS = ("read", "write", "destructive", "unknown")


def _normalize(text: str) -> str:
    """snake_case -> space-separated, so `\\b` boundaries land on every word
    of an identifier the same way they already do in a sentence."""
    return text.replace("_", " ").replace("-", " ")


def classify_tool(name: str, description: str = "") -> str:
    """One of `CLASSIFICATIONS`. Checks the destructive tier across BOTH the
    name and the description before falling back to write, and write before
    read — so a name matching "read" but a description matching "delete"
    (or vice versa) is classified by the more consequential signal, not by
    whichever text happened to be given first. A name like `run` needs the
    description to tell read from write at all; this is a name/description
    heuristic, not a lexicon — an inflection it does not recognize (e.g.
    "deletion" vs. the "delete" stem) simply does not match, which is the
    honest failure mode this module's own docstring names."""
    haystacks = [_normalize(name or "")]
    if description:
        haystacks.append(_normalize(description))
    for text in haystacks:
        if _DESTRUCTIVE_RE.search(text):
            return "destructive"
    for text in haystacks:
        if _WRITE_RE.search(text):
            return "write"
    for text in haystacks:
        if _READ_RE.search(text):
            return "read"
    return "unknown"


def default_payload(
    server_id: str, tool: str, arguments: Optional[dict[str, Any]], classification: str,
) -> dict[str, Any]:
    """The suggested `human_loop.enqueue(kind=..., payload=...)` arguments for
    a federated call this module classified as consequential. Callers decide
    whether to actually enqueue (and whether to wait for resolution before
    calling) — this only shapes what a human reviewing the queue would see:
    which server, which tool, the tier that triggered review, and the
    arguments as given (never the downstream server's response, which does
    not exist yet at the point this is built).
    """
    return {
        "kind": "federated_mcp_call",
        "summary": f"{classification}: {tool} on server {server_id}",
        "payload": {
            "server_id": server_id,
            "tool": tool,
            "classification": classification,
            "arguments": dict(arguments or {}),
        },
    }
