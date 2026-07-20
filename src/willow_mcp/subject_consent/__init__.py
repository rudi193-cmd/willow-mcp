"""subject_consent — consent for a subject who isn't the owner.

The stdlib-only, egress-free core of the guardian-consent seam
(docs/design/guardian-consent-seam.md). One shared primitive for the gap that
corpus-lens named its "biggest unshipped gap", the willow-mcp seam doc mapped,
and UTETY built privately: *did this person — or a guardian on their behalf —
agree to their data being used this way?*

Import only `willow_mcp.subject_consent.core` and you pull in nothing but the
standard library — that boundary is what lets UTETY run it on a child's device
and corpus-lens depend on it under its stdlib-only charter. The willow-mcp
binding (gate wiring, ReceiptLog) is a separate, heavier module; it may import
this core, never the other way around.
"""
from __future__ import annotations

from .core import (
    RELATIONS,
    SCOPES,
    ChainTamperError,
    Consent,
    DeidentificationError,
    Subject,
    SubjectConsentError,
    deidentify,
    grant,
    permitted,
    read_disclosures,
    record_disclosure,
    revoke,
    verify_consent_chain,
)

__all__ = [
    "SCOPES",
    "RELATIONS",
    "Subject",
    "Consent",
    "SubjectConsentError",
    "DeidentificationError",
    "ChainTamperError",
    "grant",
    "revoke",
    "permitted",
    "verify_consent_chain",
    "deidentify",
    "record_disclosure",
    "read_disclosures",
]
