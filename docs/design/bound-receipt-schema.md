---
kind: doc
name: bound-receipt-schema
description: "Canonical bound-receipt wire format (#195) — join refs, signed envelope, verification order for AT-R1 (#194) and the binding writer (#196)."
---

# Bound receipt schema (v1)

Status: **SPEC** — machine shape ships in `willow_mcp/schemas/bound_receipt.v1.schema.json` and
`willow_mcp.bound_receipt`. Writer/verifier logic is **#196**; adversarial tests are **#194**.

Parent: kill-chain **#181**. Sibling issues: **#194** (AT-R1), **#196** (binding).

---

## Purpose

One signed record ties three proof planes so a verifier does not infer that independent
logs describe the same tool call:

| Plane | Receipt field(s) | Source subsystem |
|-------|------------------|------------------|
| Identity | `agent_identity_ref` | `session_bind` check-in (capped `trust_level` + `session_id`) |
| Capability | `capability_token_ref`, `policy_or_manifest_digest` | Manifest ACL + full policy bytes |
| Tool call | `tool_call_digest`, `effect_ref_or_denial_code` | Per-call credential + gate outcome |
| Prior state | `ledger_prev`, `ledger_entry_hash` | `ReceiptLog` hash chain (Nestor-style) |

---

## Wire object

Top-level JSON object (`format` = `willow-bound-receipt/1`):

| Part | Key | Signed? | Required? |
|------|-----|---------|-----------|
| Version tag | `format` | no (structural) | yes |
| Integrity-protected body | `payload` | **yes** (see below) | yes |
| Signature envelope | `signature` | no (authenticates `payload`) | yes |
| Carried metadata | `meta` | no | no |

### `payload` (inside the signature)

All fields are required on the wire. Encoding rules are in the next section.

| Field | Source | Signed? |
|-------|--------|---------|
| `agent_identity_ref` | `bound_receipt.agent_identity_ref()` from live `session_bind` session | yes |
| `capability_token_ref` | `bound_receipt.manifest_acl_digest(manifest)` | yes |
| `policy_or_manifest_digest` | `bound_receipt.manifest_policy_digest(manifest)` | yes |
| `tool_call_digest` | `bound_receipt.tool_call_digest(session_id, app_id, tool, call_nonce)` | yes |
| `effect_ref_or_denial_code` | Outcome: `denial:<code>` or `effect:<64hex>` | yes |
| `ledger_prev` | Previous `ReceiptLog` `entry_hash` (or genesis) | yes |
| `ledger_entry_hash` | Hash of the receipt row this bound record will append / cross-link | yes |
| `signer_id` | Operator-controlled signing identity (not the agent) | yes |
| `issued_at` | RFC 3339 UTC timestamp at write time | yes |
| `expires_at` | RFC 3339 UTC; freshness bound | yes |

### `signature`

| Field | Encoding | Signed? |
|-------|----------|---------|
| `alg` | Literal `hmac-sha256` or `ed25519` (v1 writers pick one; verifier matches `alg`) | no |
| `value` | Lowercase hex (64 for HMAC-SHA256, 128 for Ed25519) | no |

`verifier_id` is **not** on the receipt: the verifier is whoever runs `verify_receipt` with
the published public key / MAC key material. Optional hint may appear in unsigned `meta.verifier_hint`.

---

## Field encodings

| Kind | Pattern | Example |
|------|---------|---------|
| Digest ref | 64 lowercase hex (SHA-256) | `a3f2…` |
| Denial | `denial:` + `[a-z0-9_]{1,64}` | `denial:gate_manifest` |
| Effect ref | `effect:` + 64 hex | `effect:deadbeef…` |
| Timestamp | ISO-8601 UTC with offset, `Z` allowed | `2026-07-31T21:00:00+00:00` |
| `signer_id` | `[a-z0-9][a-z0-9._-]{0,127}` | `willow-operator` |

Digest helpers use **JSON array** canonical forms (fixed order, `separators=(",", ":")`,
`ensure_ascii=False`) — never delimiter-joined strings (Nestor B4).

---

## Canonical serialization (signing input)

Let `P` be the payload object with keys sorted lexicographically for documentation only;
the **signed byte string** is **not** a sorted JSON object. It is:

```text
CANON = UTF-8( json.dumps(
  [
    "willow-bound-receipt/1",
    payload["agent_identity_ref"],
    payload["capability_token_ref"],
    payload["policy_or_manifest_digest"],
    payload["tool_call_digest"],
    payload["effect_ref_or_denial_code"],
    payload["ledger_prev"],
    payload["ledger_entry_hash"],
    payload["signer_id"],
    payload["issued_at"],
    payload["expires_at"],
  ],
  separators=(",", ":"),
  ensure_ascii=False,
))
```

Same logical receipt → same `CANON` → same signature. Implementations MUST use
`bound_receipt.canonical_signed_bytes(payload)`.

---

## Verification-order contract (AT-R1 / #196)

Stages are **ordered**; stop at the first failure and return a **distinguishable** `reason`:

| Stage | Code | Checks |
|-------|------|--------|
| 1 | `structural_invalid` | `format`, required keys, encodings, `meta` shape |
| 2 | `expired` | `now > expires_at` (timezone-aware UTC) |
| 3 | `ref_mismatch:<field>` | Re-derive each ref from live sources; compare to `payload` |
| 4 | `signature_invalid` | Recompute MAC/sig over `canonical_signed_bytes(payload)` |

Stage 3 runs **before** signature so a single-field payload edit with an unchanged
signature byte string fails with `ref_mismatch:<field>` (AT-R1 #194), not a generic
`signature_invalid`.

Stage 4 field names match payload keys (`agent_identity_ref`, …, `ledger_entry_hash`).

Freshness runs **before** ref/signature checks so an expired receipt fails without
crypto work.

---

## Relationship to siblings

- **#194 (AT-R1)** — table-driven mutations; each row expects one `reason` from the table above.
- **#196** — `write_receipt` / `verify_receipt` implement this spec; key custody out of agent reach.
- **#183** — `capability_token_ref` remains an ACL digest today; Biscuit may replace the derivation
  without changing payload field names.

---

## Out of scope (this document)

- OS boundary / key custody (**#181** perimeter).
- Emitting or checking signatures in production (`server.py` integration).
- Biscuit token format.
