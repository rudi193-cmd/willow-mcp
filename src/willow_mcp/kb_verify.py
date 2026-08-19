"""willow_mcp/kb_verify.py — Knowledge-base source verification and health checks.

Ports the verification patterns from 2.0's source_trail_verify and 1.9's
mem_check into willow-mcp's schema-profile-aware KB surface.  Both functions
are read-only and return a structured verdict dict with an outcome key plus
evidence — the same shape frank_verify and the canonical verify tools use.
"""
from __future__ import annotations

from typing import Optional

from . import kb_curate as kbc
from . import schema_profile as sp
from ._kb_sql import KNOWLEDGE_FIELDS, build_select, row_to_dict


def _query_records(pg, app_id: str, *, domain: Optional[str] = None,
                   limit: int = 200) -> dict:
    """Shared query: fetch KB records with schema-profile awareness.

    Returns {"records": [...], "present": [...], "unmapped": [...], "total": N}
    on success, or an error dict.
    """
    mapping = sp.resolve(pg, app_id, "knowledge", KNOWLEDGE_FIELDS)
    if "error" in mapping:
        return mapping
    fields = mapping["fields"]
    if fields["id"]["column"] is None or fields["content"]["column"] is None:
        return {"error": "schema_unusable",
                "detail": "'knowledge' table has no mappable 'id' or 'content' column"}

    select_clause, present, unmapped = build_select(KNOWLEDGE_FIELDS, fields)

    tags_col = fields["tags"]["column"]
    cols_by_name = {c.name: c for c in sp.introspect(pg, "knowledge")}
    retract_sql, retract_params = kbc.sql_exclude_retracted(tags_col, cols_by_name)

    sql = f"SELECT {select_clause} FROM knowledge WHERE 1=1{retract_sql}"  # nosec B608 - select_clause/retract_sql built from confirmed schema_profile mapping; all values are bound params
    params: list = list(retract_params)

    if domain and fields["domain"]["column"]:
        sql += f' AND "{fields["domain"]["column"]}" = %s'
        params.append(domain)
    sql += " LIMIT %s"
    params.append(limit)

    cur = pg.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()

    records = [row_to_dict(r, present, unmapped) for r in rows]
    return {"records": records, "present": present, "unmapped": unmapped,
            "total": len(records)}


def verify_sources(pg, app_id: str, *, domain: Optional[str] = None,
                   limit: int = 200) -> dict:
    """Check knowledge records for source provenance.

    Returns {outcome, total, sourced, unsourced, unsourced_records,
    recommendation}.  outcome is "pass" / "warn" / "fail".
    """
    result = _query_records(pg, app_id, domain=domain, limit=limit)
    if "error" in result:
        return result

    records = result["records"]
    unmapped = result["unmapped"]
    total = result["total"]

    if "source" in unmapped:
        return {
            "outcome": "warn",
            "total": total,
            "sourced": 0,
            "unsourced": total,
            "unsourced_records": [],
            "recommendation": ("The 'source' column is not mapped in this "
                               "schema — source verification is unavailable."),
            "_unmapped": unmapped,
        }

    sourced_count = 0
    unsourced_recs = []
    for rec in records:
        if (rec.get("source") or "").strip():
            sourced_count += 1
        else:
            unsourced_recs.append(rec)
    unsourced_count = len(unsourced_recs)

    if total == 0:
        outcome = "pass"
        recommendation = "No knowledge records found."
    elif unsourced_count == 0:
        outcome = "pass"
        recommendation = f"All {total} records have source attribution."
    elif unsourced_count / total < 0.2:
        outcome = "warn"
        recommendation = (f"{unsourced_count}/{total} records lack source "
                          "attribution.")
    else:
        outcome = "fail"
        recommendation = (f"{unsourced_count}/{total} records lack source "
                          "attribution — coverage is below 80%.")

    return {
        "outcome": outcome,
        "total": total,
        "sourced": sourced_count,
        "unsourced": unsourced_count,
        "unsourced_records": [
            {"id": r.get("id"),
             "content": (r.get("content") or "")[:120],
             "domain": r.get("domain")}
            for r in unsourced_recs[:20]
        ],
        "recommendation": recommendation,
    }


def check_health(pg, app_id: str, *, domain: Optional[str] = None,
                 limit: int = 200) -> dict:
    """Broader health check on knowledge records (mem_check analog).

    Returns {flags, recommendation, evidence}.
    """
    result = _query_records(pg, app_id, domain=domain, limit=limit)
    if "error" in result:
        return result

    records = result["records"]
    unmapped = result["unmapped"]
    total = result["total"]

    flags = []
    unsourced = 0
    domainless = 0
    content_hashes: dict[str, str] = {}
    duplicates = []

    source_mapped = "source" not in unmapped
    domain_mapped = "domain" not in unmapped

    for rec in records:
        if source_mapped and not (rec.get("source") or "").strip():
            unsourced += 1
        if domain_mapped and not (rec.get("domain") or "").strip():
            domainless += 1

        content_key = (rec.get("content") or "").strip()[:200].lower()
        if content_key in content_hashes:
            duplicates.append({
                "id": rec.get("id"),
                "duplicate_of": content_hashes[content_key],
                "content": content_key[:80],
            })
        else:
            content_hashes[content_key] = rec.get("id")

    if unsourced > 0:
        flags.append({"flag": "unsourced_records", "count": unsourced,
                       "detail": f"{unsourced}/{total} records have no source"})
    if domainless > 0:
        flags.append({"flag": "domainless_records", "count": domainless,
                       "detail": f"{domainless}/{total} records have no domain"})
    if duplicates:
        flags.append({"flag": "duplicate_content", "count": len(duplicates),
                       "detail": f"{len(duplicates)} records share content"})

    if not flags:
        recommendation = "Knowledge base is healthy — no issues found."
    elif len(flags) == 1:
        recommendation = flags[0]["detail"] + "."
    else:
        recommendation = (f"{len(flags)} issues found: "
                          + "; ".join(f["flag"] for f in flags) + ".")

    result_dict: dict = {
        "flags": flags,
        "recommendation": recommendation,
        "evidence": {
            "total": total,
            "unsourced_count": unsourced,
            "domainless_count": domainless,
            "duplicate_groups": duplicates[:10],
        },
    }
    if unmapped:
        result_dict["_unmapped"] = unmapped
    return result_dict
