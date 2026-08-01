@markdownai v1.0

# Federation Envelope Wire Format — Draft 0.1

**Status:** PROPOSAL — drafted by willow (orchestrator seat), session bf1bcefc, 2026-07-07. No force until root ratifies.
**Extends:** `constitutional/syscall-table.json` (syscall-table/v1) · `constitutional/pre-approved.json` (envelope-registry/v1.1) — both under `$WILLOW_HOME`, see `paths.envelope_registry_path` / `paths.syscall_table_path`.
**Constitutional refs:** CONST-0-3, CONST-0-6, CONST-III-2
**KB lineage:** 5F2C19AF (protocol frame) · 5B7F11AF (human-seat phasing, Phase 2 = own-bike ratified)
**Moved from the `willow` charter repo's `envelopes/federation-wire-format.md`** when the envelope registry's default home moved to `$WILLOW_HOME/constitutional/` — content unchanged below this header except the `Extends` paths.

@define-concept node: A full, independently operated stack — orchestrator, executor, ledger, and store — on one machine, under one node operator. Willow is the reference implementation; the protocol MUST NOT assume Willow internals.

@define-concept node-operator: The human root of one node. Sole issuer of that node's grants, holder of the operator key. In grant language: "root" is always local — there is no federation-wide root.

@define-concept project-head: Holder of protocol authority — versions this spec, ratifies the shared verb vocabulary, arbitrates escalations. Holds ZERO runtime authority: no project-head key can make any node execute anything.

---

## 1. What travels on the wire

Exactly four message types. Anything else is EPROTO.

| Type | Direction | What it is |
|---|---|---|
| `grant` | operator → own node (published to peers) | A federation envelope: capability over verbs, issued by a node's own root for work *requested by* a named foreign node |
| `directive` | node → node | A work request citing the grant it expects to be checked against |
| `receipt` | node → requesting node | Signed record of what actually ran: outcome, evidence, local ledger anchor |
| `refusal` | node → requesting node | errno + the mechanical reason; same ink as a receipt |

The prime invariant carries over from the local law: **a directive never grants anything.** Authority is only ever issued by a node's own operator, for their own node. A remote orchestrator asking is just asking; the answering node checks the ask against grants *its own root* issued. Pangolin (or any transport) moves bytes; it confers zero trust.

## 2. Identity and signature

- Every node has a **node keypair** (Ed25519 recommended; PGP acceptable). Every operator has a separate **operator keypair**. Node keys sign directives/receipts/refusals; operator keys sign grants. A grant signed by a node key is VOID.
- Key introduction is out-of-band and operator-to-operator (Phase 1: manual exchange; Phase 2: signed roster file per node, exchanged at onboarding). There is no CA and no web-of-trust requirement in 0.1 — the roster IS the trust set.
- Every message carries: `protocol: "willow-fed/0.1"`, `msg_id` (never reused), `from` (key fingerprint), `to` (key fingerprint), `sent_at` (UTC), `nonce`, and a detached signature over the canonical JSON form (RFC 8785 JCS) of everything else.
- Unknown signer → **EUNTRUSTED** (refuse, ledger, do not escalate — an unknown key is noise until an operator introduces it).

## 3. The grant (federation envelope)

Same shape as envelope-registry/v1.1 `envelope_schema` with four additions:

```json
{
  "id": "fedenv-{verb}-{slug}",
  "verb_id": 5,
  "verb": "pr.merge",
  "grantee_node": "<node key fingerprint>",
  "bounds": { "...": "field-by-field, exactly the verb's bounds signature" },
  "evidence_required": ["ledger_anchor", "ci_state"],
  "issued_by": "<operator key fingerprint — MUST be this node's own root>",
  "issued_at": "UTC", "expires_at": "UTC|null", "max_count": "int|null",
  "use_count_source": "local-ledger",
  "verb_table_hash": "<sha256 of the issuing node's published verb table>",
  "status": "active|proposed|expired|exhausted|revoked"
}
```

Additions vs. local schema: `grantee_node` (a key, not a fleet.json id), `evidence_required` (see §5), `verb_table_hash` (both sides must agree on which table version the verb ids mean — hash mismatch is EAMBIG, not a warning), and `use_count_source: local-ledger` (the count is derived from the *executing* node's ledger; the requester never holds the counter).

Verb vocabulary: the 14-verb table is the seed vocabulary. A node MAY implement a subset; a verb a node does not implement is ENOSYS *at that node*, which is a well-formed refusal, not an error. Extending the shared vocabulary is a protocol-head act (spec amendment), never a runtime negotiation.

## 4. Refusal semantics (errno, federated)

Local errno table carries over unchanged (ENOSYS, ENOENT, EACCES, EDQUOT, EEXPIRED, EAMBIG) with routes re-pointed: `trap_to_console` means *the executing node's own console* — never the requester's. Three federation-only additions:

| errno | Meaning | Route |
|---|---|---|
| `EUNTRUSTED` | Signer not in this node's roster | refuse + ledger, no escalation |
| `ECONFLICT` | Two legitimately-signed directives/grants from different authorities contradict | **refuse BOTH** + ledger + escalate to both operators and project head |
| `EPROTO` | Malformed message, bad signature, unknown type, canonicalization failure | refuse + ledger |

ECONFLICT is the constitutional one: a node presented with conflicting legitimate authority does not pick a winner. It stops, records, and escalates. No key — including the project head's — can break the tie at runtime; humans re-issue non-conflicting grants.

## 5. Evidence and receipts

A receipt is signed by the executing node's key and contains: `directive_msg_id`, `grant_id` cited, `outcome` (granted+result | errno), `evidence` (each class the grant's `evidence_required` demanded), and `ledger_anchor` — the hash-chain entry id in the executing node's own ledger, written *before* the action executed, exactly like local envelope_citation.

Evidence classes in 0.1: `ledger_anchor` (mandatory, always), `ci_state` (named check contexts + conclusions at execution time), `artifact_hash` (sha256 of produced artifact), `command_transcript` (bounded stdout/stderr). Evidence is *checked, not asserted*: `requires_ci: true` means the receipt must carry the actual check state the node observed, and the requester may audit it later against the public record.

Receipts and refusals get the same ink — a refused directive produces a signed refusal with the errno and (for EAMBIG) the field-level diff. Silence is the only protocol violation a node can commit.

## 6. Authority does not widen in transit

Verb 11's law, federated: a directive carries the citation of the grant the requester *believes* covers it. The executing node checks against its own registry regardless of what the directive claims. A node that receives work and sub-dispatches it locally checks its local agents against its *local* envelopes — federation grants never flow downhill into a node's internal rings. Two independent checks, two ledgers, by design.

## 7. Minimum conforming node ("own bike" checklist — Phase 2 gate)

A stack conforms to willow-fed/0.1 iff it can:

1. Hold a node keypair and roster; verify Ed25519/PGP detached signatures over JCS-canonical JSON.
2. Publish a verb table (any subset of the seed 14) and its hash.
3. Match directive args against grant bounds **field-by-field, mechanically** — near-miss is EAMBIG, never a stretch.
4. Refuse with the correct errno, including ECONFLICT's refuse-both behavior.
5. Write an append-only, hash-chained local ledger entry before every execution, and emit signed receipts/refusals carrying the ledger anchor.
6. Keep its operator key off the node — grants are issued by a human act, not by the stack.

Nothing here requires Willow. That is the point: Phase 2 operators install *a* reference stack, generate their own keys, and their machines are theirs. The proper test (KB 5F2C19AF) is a non-Willow stack passing this list.

## 8. Out of scope for 0.1

Transport and discovery (Pangolin assumed, anything works) · payload semantics beyond verb bounds · key rotation/revocation ceremonies (Phase 1.5 exercise) · quorum/multi-party grants · economic metering. Each becomes a numbered amendment when a phase forces it.

@constraint A grant may only be issued by the operator key of the node that will execute the work. Cross-issued grants are VOID regardless of signature validity.
@constraint ECONFLICT resolution is human-only. No runtime actor, including project head, may arbitrate conflicting legitimate authority.
@constraint Every directive outcome — granted or refused — produces a signed, ledger-anchored response. Silence is a protocol violation.

---

*Lineage: single-machine envelope law drafted 2026-07-06 (session e2b05d0a, FRANK 6ba8e501); federation frame + human-seat phasing decided 2026-07-07 (session bf1bcefc, KB 5F2C19AF / 5B7F11AF, Grove #264). This draft is the "one-page wire-format spec" named there as the next bite.*
