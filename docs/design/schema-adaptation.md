# Design: Schema Adaptation for External Data — Databases and Identity Claims

Status: DRAFT — §§1–5, 7–9 not yet implemented or ratified. **§6.3's core
binding mechanism (`identity_binding.py`) has since shipped** — see the
correction note at the top of §6 before reading it as a problem statement.
Author: Ada (fleet id: willow), 2026-07-08, following operator design conversation.
Motivating incidents (two, same root cause at the time this doc was drafted):

1. PR #3 smoke test — `knowledge_search`, `kb_startup_continuity`, and `kb_at`
   crashed with `UndefinedColumn: "source"` against a real production `knowledge`
   table; `fleet_health` crashed with `UndefinedTable: "kart_task_queue"`.
   Root cause: `server.py` hardcodes column/table names for tables it does not
   own and never created. `fleet_status` succeeded in the same test, because it
   happened to match the real `agents` table by coincidence — proving the tool
   *can* usefully read a live host schema when the assumption is right, and
   crashes hard when it isn't. **Still true as of 2026-07-08** — verified
   against a live schema; see §1 (unchanged).
2. OAuth review (earlier the same day this doc was drafted) — at the time,
   `oauth.py`'s Google and Apple callbacks appeared to verify identity,
   compute `(email, sub)`, and discard it. **This turned out to be wrong on
   closer reading** — a later same-day code read found the identity *is*
   attached to the issued token and *is* read by `gate.py`; see the
   correction note at the top of §6. What's still true, and still motivates
   §6 as a design: Google's `tokeninfo` response and Apple's JWT payload are
   two different, divergent shapes for "who signed in" — that framing holds
   independent of whether the binding code existed yet.

See conversation log for the full reasoning trail on both.

## 1. Problem statement

willow-mcp is meant to be pointed at **someone else's** database, not its own.
The operator gave three concrete tiers of "someone else":

1. **A builder with scattered DBs/KBs** — several personal projects, each with
   a knowledge or task table that evolved independently. Schemas are similar
   in spirit, diverged in detail (`source` vs `source_type` vs `origin_ref`).
2. **A mid-size office with decades of databases** — provenance is unclear,
   nobody currently on staff necessarily knows what a given table means or
   who last touched it. Some tables may be load-bearing for processes nobody
   has documented.
3. **A DOD contractor, or DOD itself** — the stakes tier. Wrong writes are not
   an inconvenience, they are potentially a compliance or safety incident.
   Every read and write needs to be defensible after the fact.

Across all three, the common shape is the same: **willow-mcp does not get to
assume it knows what a table means.** It has to find out, say what it found,
and treat writing into an inference as a categorically different — and much
more dangerous — action than reading from one.

This rules out both options considered earlier in the conversation:

- **Self-provisioned isolated schema** (`willow_mcp.*` namespace, own tables) —
  wrong, because then the tool never actually engages with the host's real
  data. It solves the crash but defeats the entire premise of "works with any
  codebase."
- **Hardcoded column names** (today's code) — wrong, demonstrably: it crashes
  the instant the host schema doesn't match the author's assumption, and by
  tier 2 above, nobody may be positioned to notice it silently returned
  wrong data instead of crashing.

## 2. Design principles

1. **Discover, don't assume.** Before any tool issues SQL against a host
   table, it queries `information_schema` for that table's real columns and
   types. No query string embeds a column name that wasn't confirmed to
   exist in *this* database, *this* run.
2. **Map to canonical concepts, with visible confidence.** willow-mcp's tools
   speak in canonical fields (`id`, `content`, `domain`, `source`, `tags`,
   `created_at`, …). A per-database **mapping** translates canonical fields to
   whatever the host schema actually calls them, using name/type heuristics
   (aliases, substring match, type compatibility). Every mapped field carries
   a confidence tier (`exact` / `alias` / `inferred` / `unmapped`) — this is
   surfaced to the caller, never hidden.
3. **Reads may infer. Writes may not guess.** A read using an `inferred`
   mapping degrades gracefully — missing fields come back `null` or omitted,
   annotated with which mapping tier produced them, rather than raising. A
   write is refused unless the target column's mapping has been explicitly
   confirmed (see §4) for that specific table in that specific database.
   This is the load-bearing safety rule for tiers 2 and 3 above.
4. **The mapping is an artifact, not a black box.** Once computed, a mapping
   is written to a reviewable, editable file (see §5) — not held only in
   memory, not silently re-guessed differently on the next run. A human (or
   an audit process) can read exactly what willow-mcp believes a table's
   columns mean, correct it, and have the correction persist and take
   precedence over the heuristic from then on.
5. **Every inference is logged.** Which columns were discovered, what they
   were mapped to, at what confidence, and — critically — what mapping was
   *in effect* at the time of any write. This is the same tamper-evident
   posture as the fleet's own FRANK ledger: the log is what makes an
   inference defensible after the fact, which matters most exactly in tier 3.

## 3. Architecture sketch

```
                 ┌─────────────────────┐
   tool call ───▶│  canonical query     │   e.g. knowledge_search(app_id, query)
                 │  (server.py)         │
                 └──────────┬───────────┘
                            ▼
                 ┌─────────────────────┐
                 │  SchemaProfile       │   per (db, table) — cached, file-backed
                 │  .resolve(table)     │
                 └──────────┬───────────┘
                            │  cache miss / stale?
                            ▼
                 ┌─────────────────────┐
                 │  introspect()        │   information_schema.columns
                 │  + propose_mapping() │   canonical → real column, w/ confidence
                 └──────────┬───────────┘
                            ▼
                 ┌─────────────────────┐
                 │  mapping artifact    │   $WILLOW_HOME/mcp_apps/<app_id>/
                 │  (reviewable JSON)   │   schema_maps/<db_fingerprint>.json
                 └──────────┬───────────┘
                            ▼
                 ┌─────────────────────┐
                 │  query builder       │   builds SQL only from confirmed-
                 │  (read vs write path)│   present columns; write path checks
                 └──────────┬───────────┘   mapping.confirmed before allowing
                            ▼
                     SQL against host DB
```

### 3.1 `SchemaProfile`

A small module (`schema_profile.py`) responsible for:

- `introspect(conn, table) -> list[ColumnInfo]` — one `information_schema`
  query per table, cached in-process per connection lifetime.
- `propose_mapping(columns, canonical_fields) -> Mapping` — heuristic pass:
  exact name match → known aliases (`source_type`, `origin`, `origin_ref` →
  `source`; `body`, `text` → `content`; …) → type-compatible best-effort guess
  → unmapped. Each field in the returned `Mapping` carries `{column, tier,
  confidence}` or `None` if nothing plausible was found.
- `load_confirmed(app_id, db_fingerprint, table) -> Mapping | None` — reads a
  previously-saved, human-reviewed mapping if one exists; this always wins
  over a fresh heuristic guess.
- `db_fingerprint(conn)` — stable identifier for "this database" (e.g. hash
  of host + dbname, not connection-string secrets) used as the mapping
  artifact's key, so the same database is recognized across restarts even if
  reached via a different app_id.

### 3.2 Mapping artifact

Stored at `$WILLOW_HOME/mcp_apps/<app_id>/schema_maps/<db_fingerprint>__<table>.json`:

```json
{
  "schema_version": 1,
  "database": "postgres://host/dbname",
  "table": "knowledge",
  "discovered_at": "2026-07-08T03:40:00Z",
  "confirmed": false,
  "fields": {
    "id":         {"column": "id",          "tier": "exact"},
    "content":    {"column": "content",     "tier": "exact"},
    "domain":     {"column": "domain",      "tier": "exact"},
    "source":     {"column": "source_type", "tier": "alias", "confidence": 0.9},
    "tags":       {"column": null,          "tier": "unmapped"}
  }
}
```

`schema_version` exists so a mapping artifact is legible as *which declared
shape* produced it — required for alignment with the cross-project
shape-projection contract; see §9.

`confirmed` starts `false` (heuristic only). A human — or an explicit
`schema_confirm_mapping` tool call gated the same way `knowledge_ingest` is
gated today — flips it to `true`, optionally editing individual field
mappings first. Only `confirmed: true` mappings unlock write tools for that
table. This file is plain JSON specifically so it's diffable, greppable, and
reviewable without a special tool — an auditor in tier 3 can read it cold.

### 3.3 Read path

`knowledge_search`, `kb_at`, `kb_startup_continuity`, `fleet_health`, etc.
build their `SELECT` column list from `mapping` at call time, using whatever
real column names were discovered — `exact`, `alias`, or `inferred` tiers all
participate in reads. A canonical field with `tier: unmapped` is simply
omitted from the result (or returned as `null` with a `"_unmapped": [...]`
marker) rather than raising `UndefinedColumn`. This directly fixes today's
crash: `source` unmapped or aliased to `source_type` never produces bad SQL.

### 3.4 Write path

`knowledge_ingest`, `kb_promote`, `kb_journal`, and any future write tool
check, per targeted column, that the mapping for that field is `confirmed:
true`. If not:

```json
{"error": "unconfirmed_schema: field 'source' on table 'knowledge' has not "
          "been confirmed for this database — call schema_confirm_mapping "
          "or edit the mapping file directly, then retry"}
```

No silent best-effort writes, ever. This is the tier-2/tier-3 safety
boundary: reads can be helpful-and-approximate, writes must be
correct-or-refused.

### 3.5 Relationship to `gate.py`

`gate.py`'s manifest ACL answers "may this `app_id` call this *tool*."
Schema confirmation answers a narrower question underneath that: "may this
*write* proceed against this *table*, in *this* database, given what we
currently believe its columns mean." Both checks apply — a caller can be
permitted the `knowledge_write` group and still be refused a specific write
because the mapping for that host table isn't confirmed yet. These are
independent, composable gates, not a replacement for one another.

## 4. Degradation & error behavior

- Table introspection fails entirely (no such table) → tool returns
  `{"error": "table_not_found: <table>"}`, no exception surfaces to the
  transport.
- Table exists, canonical field unmapped → read omits/nulls that field,
  annotates `_unmapped`; write touching that field is refused per §3.4.
- Mapping file present but stale (host schema has since changed columns) →
  re-introspect, diff against the saved mapping, and if the *confirmed*
  mapping's columns no longer exist, downgrade `confirmed` to `false` and
  surface a `schema_drift` warning rather than writing against columns that
  may no longer mean what a human confirmed them to mean.

## 5. Audit logging

Every introspection, every mapping proposal, every confirmation, and every
write's *effective mapping at time of write* gets an entry in a local
append-only log (candidate: reuse the existing FRANK ledger pattern from
willow-2.0, or a lighter per-app JSONL under `$WILLOW_HOME/mcp_apps/<app_id>/
schema_audit.jsonl` if willow-mcp shouldn't depend on FRANK directly for a
public-facing package). Minimum fields: timestamp, app_id, table, mapping
snapshot, tool called, confirmed-by (human/heuristic).

## 6. A second instance of the same problem: OAuth identity claims

**Correction (2026-07-08, same day, later pass):** this section originally
opened on the premise that identity binding didn't exist yet — verified
false on a direct re-read of `oauth.py`, `identity_binding.py`, and
`server.py`. **§6.3's binding mechanism is already built and wired**:
`propose_binding` / `confirm_binding` / `resolve_app_id` in
`identity_binding.py` implement steps 1–3 below exactly, and
`server.py`'s `_resolve_serve_identity()` already calls `resolve_app_id`
before `gate.permitted()` runs, fail-closed. See KB atom `E46DB231`
(canonical, supersedes the stale claim that identity is "verified then
discarded") for the full trace. What's still open, scoped down from the
original problem statement: **§6.2's `email_basis`-aware canonical identity
record does not exist** (today's code passes a raw `email` string with no
provenance tag), and **§6.3 step 4's drift detection is not implemented**
(a changed email for an existing `(issuer, subject_id)` is silently accepted
rather than flagged). The rest of this section is kept for the parts still
worth building, with each subsection marked done/open below.

The operator's original observation still holds as the reason this section
exists at all: a host Postgres database is an external schema willow-mcp
must not assume it understands, and an identity provider's claims are the
same kind of thing — Google and Apple each hand back "who signed in" in a
different shape, and §§1–5 above apply almost unchanged if "table" is read
as "identity provider" and "column" as "claim." That framing motivated
building the binding mechanism that now exists; it was never wrong, only
the "nothing has been built yet" framing around it was.

### 6.1 The two claim shapes, as they exist today

- **Google** (`_google_verify_id_token`, `oauth.py:237`): calls the
  `tokeninfo` endpoint, gets back flat JSON — `email` (string),
  `email_verified` (the *string* `"true"`/`"false"`, not a bool — a schema
  wrinkle in its own right), `sub` (stable per-account id), `aud`. Email is
  always present if the scope was granted.
- **Apple** (`_apple_verify_id_token`, `oauth.py:277`): a self-verified JWT —
  `sub` (stable per-app-and-account id, *not* stable across different client
  apps for the same person), `email` (present only on the *first*
  authorization ever, silently absent on every subsequent one unless the
  client cached it), optionally a private relay address instead of a real
  one, no `email_verified` claim at all (trust is implied entirely by
  signature verification against Apple's JWKS).

**Status: partially open.** `sub` is used correctly today — it's attached to
the issued token and drives the identity binding (§6.3, done). `email` is
still handled as one undifferentiated shape: `oauth.py` passes it straight
into `propose_binding(issuer, sub, email)` with no marker for how much it
should be trusted. Code written against Google's always-present, IdP-asserted
`email` will silently misbehave the first time Apple's is absent or a relay
address — that specific risk (§6.2's `email_basis`) has not been fixed, only
the larger "identity is discarded" claim was wrong.

### 6.2 Canonical identity mapping — **status: not built**

Same move as §3.1, applied to identity instead of table columns. A canonical
identity record:

```json
{
  "issuer": "google" | "apple",
  "subject_id": "<sub, stable per issuer+client>",
  "email": "<string or null>",
  "email_basis": "asserted" | "first_auth_only" | "relay" | "unavailable",
  "verified_at": "2026-07-08T04:00:00Z"
}
```

`email_basis` exists because "do we have an email" is not the interesting
question — "how much should anything downstream trust this email" is.
Google's is IdP-asserted every time; Apple's may be a one-time snapshot or a
relay address that silently stops forwarding if the user revokes it later.
Collapsing these into one `email: str` field, as today's code implicitly
does, is the identity equivalent of assuming every database's `source` column
is spelled the same way.

### 6.3 The write path: binding identity to an app_id — **status: built (steps 1–3), step 4 open**

This is where §3.4's "reads may infer, writes may not guess" rule matters
most, because the "write" here is not a database row — it's **granting a
human standing under `gate.py`**, a more consequential action than any single
`knowledge_ingest` call. This is now implemented: `identity_binding.py`'s
docstring cites this section directly, and `_resolve_serve_identity()` in
`server.py` calls `resolve_app_id()` before any tool dispatch, fail-closed.

Flow as built, mirroring §3.2–§3.4:

1. **Done.** First sign-in for a given `(issuer, subject_id)` calls
   `propose_binding(issuer, subject_id, email)` — a record with `app_id:
   null, confirmed: false` is written, but no standing is granted. The access
   token is still issued (transport-layer OAuth completes, per spec); every
   subsequent tool call gates as unauthenticated until a binding is
   confirmed. (Gap: the record stores raw `email`, not the §6.2 canonical
   form with `email_basis` — see §6.2.)
2. **Done.** The proposed binding is written to a reviewable artifact:
   `$WILLOW_HOME/mcp_apps/_identity_bindings/<issuer>__<subject_id>.json`,
   `confirmed: false` until the operator runs `willow-mcp confirm-binding`
   (local, stdio-only CLI subcommand — intentionally **not** an MCP tool, so
   a remote serve-mode caller can never confirm their own binding; stricter
   than the `identity_confirm_binding` MCP-tool shape originally proposed
   here, and better for it).
3. **Done.** Only a `confirmed: true` binding lets `_gate()` resolve an
   OAuth-session token to an `app_id` — `resolve_app_id()` returns `None`
   (fail-closed) for anything unconfirmed. Stdio and serve mode now behave
   consistently: both fail closed on missing standing, where serve mode
   previously didn't check at all.
4. **Not implemented.** `propose_binding` returns the existing record
   untouched on a repeat sign-in (correct — a human's prior decision must
   never be silently overwritten), but nothing compares the incoming
   `email` against the bound record's stored `email` to detect drift. If
   `subject_id` later maps to a *different* email than the bound record
   shows, that should be surfaced the same way §4 surfaces `schema_drift` —
   today it's silently accepted. If Apple's `email` disappears on a later
   login (expected — see §6.1) that is correctly *not* drift (`subject_id` is
   unchanged), so this needs to check "email present and different," not
   "email present and different-from-null."

### 6.4 Relationship to §3.5 and to OAuth scope

Two independent gates compose here, same as §3.5: the OAuth `scope` (today a
single flat `"willow"` — see conversation log) says what a *token* is allowed
to request; the identity binding (§6.3) says what *human* the token speaks
for and what `app_id` standing that grants. Widening scope past the single
flat value (e.g. per-`PERMISSION_GROUPS` scopes, so a client can request
`knowledge_read` specifically rather than blanket `willow`) is a real
improvement but a distinct piece of work from binding — a token could have a
correctly narrow scope and still be bound to nobody, which is exactly
today's state.

## 7. Cross-project alignment: the shape-projection contract (ledger `0ba6a33f`)

A separate project (shape-projection / consent-lease design, ledger
`0ba6a33f`) defines a 4-point contract for how a per-source field shape gets
turned into a consent-scoped release of data. willow-mcp's schema layer
(§§1–5) is a sibling of that contract, not an independent design — the same
primitives should hold in both, because both are answering the same
question: "given a real-world source with a real shape, what may leave, in
what form, and how do we prove later that it was permitted." This section
maps the contract onto what's already specified above and flags the deltas.

The 4 points, and where each lands:

1. **Declarative per-source field schema, versioned. Not inferred at
   runtime, not an LLM guess.**
   This is the `SchemaProfile` mapping artifact (§3.1–§3.2) — the `SCHEMA`
   object. It already matches the spirit: introspected once via
   `information_schema`, written to a reviewable file, never re-guessed
   silently on a later run once confirmed. The delta: it needed an explicit
   version marker to be legible as "which declared shape produced this," so
   `schema_version` was added to the mapping artifact JSON in §3.2. A schema
   is versioned by table+database (`db_fingerprint`, §3.1), same unit the
   contract calls a "source."

2. **Projection = allow-listed field subset + per-field transform level. An
   allow-list, never a deny-list. Kept as a separate object from the
   schema.**
   This is **not yet modeled** in §§1–5 and must not be collapsed into the
   `SchemaProfile` mapping. The mapping answers "what does this table's
   column called `X` actually mean" (what exists). A `PROJECTION` answers a
   different question: "of the fields this SCHEMA says exist, which ones may
   this particular caller/destination/purpose see, and at what
   transform level (`full` | a named transform, e.g. `first-name-only` |
   `DROP`)." A `PROJECTION` is defined *against* a confirmed `SCHEMA` (§3.2's
   `confirmed: true`) — it can only allow-list fields the schema already
   knows about; see point 4. Concretely, this becomes a second artifact type
   alongside the mapping file:
   `$WILLOW_HOME/mcp_apps/<app_id>/schema_maps/<db_fingerprint>__<table>__projection__<purpose>.json`,
   `{schema_version, fields: {field: "full"|"<transform-name>"|"DROP"}, destination, purpose}`.
   Read/write tools in §§3.3–3.4 operate against the `SCHEMA`; anything that
   *leaves* willow-mcp's boundary (a future export, a federation grant, a
   response handed to a different agent than the one that authored the
   mapping) must additionally pass through the relevant `PROJECTION` for that
   destination+purpose. Nothing in §§1–6 currently leaves the boundary this
   way, so no code changes are required yet — but any future tool that does
   (e.g. a federation-facing read, or willow-mcp fronting Gmail/Calendar/Drive
   as described in the shape-projection project) must be built with a
   `PROJECTION` object from day one, not retrofitted.

3. **Deterministic signature hash = the shape id. Hash over (source,
   projection, destination, purpose). Same shape → same hash → the lease
   keeps muting the same ask.**
   willow-mcp does not yet issue or check consent leases — that machinery
   lives in the other project. The alignment obligation here is narrower:
   when a `PROJECTION` artifact (point 2) is created, it must be hashable
   into the same shape-id form the other project expects, so a consent lease
   minted there can bind to a projection defined here. Concretely: `shape_id
   = sha256(canonical_json({source: db_fingerprint+table+schema_version,
   projection: projection_fields, destination, purpose}))`. This is a pure
   function of the artifact's own fields — no willow-mcp-internal state (no
   timestamps, no row data) may enter the hash, or the "same shape → same
   hash" property breaks.

4. **Fail-closed on any field absent from the declared schema. A field not
   in SCHEMA is dropped / re-asks by default, because PROJECTION is an
   allow-list.**
   This is already the load-bearing rule of §3.4 (writes refuse on
   unconfirmed mapping) and §4 (schema drift downgrades `confirmed` to
   `false` rather than trusting stale columns) — extend it explicitly to
   `PROJECTION` once that object exists: a `PROJECTION` may only name fields
   present in its `SCHEMA`'s `fields` map at the `SCHEMA`'s current
   `schema_version`. A column that shows up in a live introspection but
   isn't yet in the confirmed `SCHEMA` is invisible to every `PROJECTION` —
   it cannot be allow-listed by omission, accident, or a projection author
   assuming a field exists. This is the same posture as §4's
   `schema_drift`: a new column widens what *could* be mapped, never what
   *is* released, until a human confirms it into the `SCHEMA` first.

**Cross-cutting rule, restated for this codebase:** `SchemaProfile` /
mapping artifact (§3.2) and any future `PROJECTION` artifact (point 2 above)
are separate files with separate confirmation gates — a `schema_confirm_mapping`
call (§8) changes only what willow-mcp believes a table means; it never
implicitly grants a projection. Collapsing them (e.g. treating "column is
mapped" as "column may leave") would silently reintroduce a deny-list-shaped
bug into an allow-list-shaped design.

## 8. Open questions (for next pass, not blocking the write-up)

- **Aliasing dictionary scope.** Should common aliases (`source`/`source_type`/
  `origin`) ship as a static built-in list, or be per-deployment configurable?
  Static-but-extensible seems right; a config override file is cheap to add.
- **Who can call `schema_confirm_mapping`?** Presumably gated at least as
  strictly as `knowledge_write` — arguably its own permission group, since
  confirming a mapping is a more consequential act than a single write.
- **Cross-database identity for `db_fingerprint`.** Needs to be careful not
  to leak connection secrets into a mapping filename or content, while still
  being stable enough to recognize "the same database" across restarts.
- **SQLite `Store` tools are unaffected** — they already own their schema
  (`records` table, created by `Store.__init__`), so none of this applies to
  `store_*`. This design is scoped to the Postgres-backed tools only
  (`knowledge_*`, `kb_*`, `task_*`, `agent_*`, `fleet_*`).
- **Performance** — introspection + mapping resolution should be cached per
  connection/process lifetime (not re-queried per call), invalidated only on
  detected schema drift (§4) or explicit cache-bust.
- **Who can call `identity_confirm_binding`?** (§6.3) Almost certainly a
  narrower circle than `schema_confirm_mapping` — binding a human to
  standing is closer to an admin action than a data-schema decision. Possibly
  restricted to stdio-mode, local-filesystem confirmation only, so a serve-mode
  remote caller can never confirm their own binding.
- **First-run bootstrap.** If `--serve` mode's very first user has no bindings
  file at all, how does *anyone* get bound without a chicken-and-egg problem?
  Likely answer: the operator pre-seeds one binding for themselves via stdio
  before ever exposing `--serve`, same way the very first `mcp_apps/<app_id>/
  manifest.json` had to be hand-written this session (§3.2's `willow` manifest).
- **Apple `sub` non-portability.** Apple's `sub` is scoped per (team_id,
  client_id) pair by design — the same person signing in through two
  different registered Apple apps gets two different `sub` values. The
  canonical identity record's `subject_id` should probably be namespaced as
  `(issuer, apple_team_id, apple_client_id, sub)` for Apple specifically, not
  just `(issuer, sub)`, or a legitimate re-registration will look like a new
  identity.
- **`PROJECTION` object build order.** (§7) Not scheduled in §9's rollout
  because nothing in scope yet leaves willow-mcp's boundary — but the first
  tool that does (federation-facing read, or a future Gmail/Calendar/Drive
  connector) must not ship without one. Track as a prerequisite gate on that
  work, not as its own standalone rollout step here.

## 9. Rollout shape (sketch, not committed)

1. `schema_profile.py` — introspection + heuristic mapping + artifact
   read/write, unit-tested against a handful of synthetic schemas (matching
   column, aliased column, missing column, extra columns).
2. Wire read tools (`knowledge_search`, `kb_at`, `kb_startup_continuity`,
   `fleet_health`) through the mapping instead of hardcoded SQL — this alone
   fixes today's crash and is safe to ship independently.
3. Add `schema_confirm_mapping` tool + write-path gate for
   `knowledge_ingest` / `kb_journal` / `kb_promote`.
4. Add audit logging.
5. Only after the above: revisit `task_*`/`agent_*` tools, which currently
   assume a `kart_task_queue` / `routing_decisions` shape that may not exist
   at all in a host database — same introspect-or-refuse treatment, plus a
   decision on whether willow-mcp should be allowed to *create* a task queue
   table when none exists (a write-time question, not a read-time one, and
   arguably its own consent gate distinct from schema confirmation).
6. **Done, independently of 1–5.** The identity-binding artifact and gate
   wiring (§6.3 steps 1–3) shipped: `identity_binding.py` implements
   `propose_binding` / `confirm_binding` / `resolve_app_id`, and
   `server.py`'s `_resolve_serve_identity()` calls `resolve_app_id()` before
   `gate.permitted()` — a serve-mode caller with no confirmed binding is
   denied the same as an unmanifested stdio `app_id`. Confirmation is the
   local-only `willow-mcp confirm-binding` CLI subcommand, not an MCP tool
   (stricter than this doc's original `identity_confirm_binding` MCP-tool
   proposal). **Remaining, not yet built:** the §6.2 canonical identity
   record (`email_basis` tracking — Google vs Apple email trust differs and
   today's code doesn't distinguish them) and §6.3 step 4 (drift detection
   when a `(issuer, subject_id)` binding's email changes between sign-ins).
   Both are small, scoped additions to the existing `identity_binding.py`,
   not new architecture.
7. Only after 6's remaining pieces: widen OAuth scope past the single flat
   `"willow"` value (§6.4) to mirror `PERMISSION_GROUPS`, so a client can
   request narrower access than "everything this human is bound to."
   Sequenced last because a finer-grained scope on top of drift-blind
   binding is polish on a foundation with a known gap, not a foundation
   that isn't there — the ordering rationale changed, the ordering itself
   didn't.

4d (PyPI publish) should wait on step 2 (read-path schema fix, still open)
and on closing 6's remaining email-drift gap — publishing with OAuth login
that authenticates a real human and then silently accepts a changed email
on an existing binding is a smaller but still real gap to ship with, not
the "silently fails to authorize anyone" gap originally described here
(that part is already fixed).
