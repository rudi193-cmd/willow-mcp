"""Canonical fleet roles — loader for specialist registry.

Identity, mandate, and persona paths: docs/design/specialist-registry.md
Tool permissions per role: NOT DECIDED — allow/deny lists below are legacy sketches only.
"""

from __future__ import annotations

ROLE_ENVELOPES: dict[str, dict] = {
    "willow": {
        "title": "Orchestrator",
        "job": "Own DAG, dispatch, verify, report to operator",
        "not": "Implementation without envelope grant",
    },
    "hanuman": {
        "title": "Builder",
        "job": "Code, builds, tests, Kart — worktree + PR",
        "not": "Direct master commits",
        "allow_tools": ["task_submit", "task_status", "task_list", "context_save", "context_get"],
        "deny_tools": ["kb_promote", "knowledge_ingest"],
    },
    "jeles": {
        "title": "Head Librarian",
        "job": "Retrieval, citation, sourced synthesis, KB verification",
        "not": "Designer, builder, ADR author",
        "allow_tools": ["knowledge_search", "kb_at", "handoff_write_v4", "context_save", "context_get"],
        "deny_tools": ["task_submit", "knowledge_ingest", "kb_journal", "kb_promote"],
    },
    "loki": {
        "title": "Auditor",
        "job": "Gap analysis, adversarial review, specific findings",
        "not": "Build, KB writes",
        "allow_tools": ["knowledge_search", "kb_at", "handoff_write_v4", "context_save", "context_get"],
        "deny_tools": ["task_submit", "knowledge_ingest", "knowledge_ingest", "store_put", "store_update"],
    },
    "ada": {
        "title": "Keeper of Quiet Uptime",
        "job": "Monitor-first, diagnostics, Almanac reachability",
        "not": "Change agent",
        "allow_tools": ["fleet_health", "fleet_status", "diagnostic_summary", "handoff_write_v4"],
        "deny_tools": ["task_submit", "store_put", "store_update", "knowledge_ingest"],
    },
}

VALID_STATUSES = frozenset({
    "pending", "working", "complete", "verified", "cleared", "closed", "failed",
})


def role_info(role: str) -> dict | None:
    return ROLE_ENVELOPES.get((role or "").lower())
