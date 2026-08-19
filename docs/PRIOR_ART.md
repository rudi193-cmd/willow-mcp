# Prior art — MCP ecosystem survey

A survey of what already exists for the machinery willow-mcp builds on,
filtered to licences an Apache-2.0 repo can depend on.

**The licence filter is hard.** MIT, BSD, ISC, Unlicense, Zlib, Boost and
Apache-2.0 are all one-way compatible: we can depend on them. MPL-2.0 and
EPL-2.0 are file-level copyleft and are fine as dependencies but want a look.
GPL, LGPL and AGPL are out for anything we redistribute — they are listed
anyway, so the cost of not using them is visible rather than invisible.

**Verification standard.** Licences below were checked against the actual repo
or registry metadata by the agents that surveyed them. Where that could not be
done, the entry says so. Treat an unverified licence as unknown, not as
permissive.

---

## 1. MCP tool shapes — the field vs willow-mcp

Surveyed 2026-08-18. The question: what do the most-used MCP servers look like,
how does `willow-mcp`'s ~110-tool surface compare, and where Apache-compatible
alternatives exist for the shapes it is missing.

### The field

Servers cluster into three archetypes:

- **Platform servers** (GitHub, Linear, Notion, Slack, Jira) — 15–50 tools,
  typed per-entity CRUD, domain-scoped search, read-dominant surfaces. Dangerous
  verbs are gated or absent.
- **Instrument servers** (Playwright, Filesystem, Puppeteer) — 14–60 tools,
  session-scoped imperative actions, explicit state handles.
- **Pipe servers** (Fetch, Brave Search, Postgres) — 1–2 tools, pass-through to
  one backend, minimal surface.

Seven patterns repeat across the popular servers: domain-scoped search,
read-dominant tool ratios, dangerous verbs gated or absent, one-tool-per-verb vs
SQL-pass-through as a deliberate fork, Markdown as content interchange, explicit
threading/hierarchy, and typed per-entity CRUD.

### Shape gaps between willow-mcp and the field

Seven gaps where popular MCP servers carry shapes willow-mcp does not:

| Gap | Best internal prior art | Best Apache-compatible alternative | Call |
| --- | --- | --- | --- |
| Threading / reply-to | Grove `grove_reply`/`grove_get_thread` (1.9 + 2.0, FK-backed `reply_to_id`) | [Monadical-SAS/zulip-mcp](https://github.com/Monadical-SAS/zulip-mcp) (Apache-2.0, topic-based) | **Build** |
| Draft / schedule writes | `*_schedule` condition-gated facades (2.0), law-gazelle drafts (safe-app-store) | Discourse MCP draft tools (licence unconfirmed on wrapper) | **Build** |
| Staged approval state machines | `gap_*` three-state machine (willow-mcp, shipped PR #54), `mem_binder` (2.0) | [Netflix Conductor](https://github.com/Netflix/conductor) (Apache-2.0) | **Adapt** |
| Cursor pagination | Grove `since_id` keyset cursor (1.9) | MCP spec itself + SDK (MIT) | **Spec** |
| Block-level content | None in any version | [Editor.js](https://github.com/codex-team/editor.js) (Apache-2.0, headless block model) | **Adapt** |
| ~~MCP tool annotations~~ | Full coverage in 2.0; **all 142 tools in willow-mcp** | MCP spec guidance (blog 2026-03-16) | ~~**Spec**~~ done |
| Source verification | `source_trail_verify` (2.0), `mem_check` (1.9) | [ClaimsMCP](https://github.com/AdamGustavsson/ClaimsMCP) (Apache-2.0, claim extraction) | **Build** |

**Build** = no viable drop-in; build from internal prior art.
**Adapt** = external alternative exists but needs wrapping.
**Spec** = already defined in the MCP protocol; follow it.

### How the prior art wires across repos

Threading evolved but never consolidated. `willow-1.9/grove/mcp_local.py`
defines `grove_reply(channel, content, sender, reply_to_id)` against a
`messages.reply_to_id BIGINT REFERENCES messages(id)` FK column, and
`grove_get_thread(message_id)` returns `{parent, flags, replies}`.
`willow-2.0/sap/grove_tools.py` carries the same two functions byte-for-byte.
Separately, 2.0's `agent_dispatch` added its own `dispatch_tasks.reply_to` — but
as bare TEXT (no FK, no index), carrying the requesting `app_id` for lineage
bookkeeping, not for thread retrieval. The two threading models coexist in 2.0
without interacting. `safe-app-store` carries a third attempt: every app has an
identical `safe_integration.py` with `send(to_app, subject, body,
thread_id=None)` / `check_inbox()` — a Pigeon bus stub, fully dead
(`"porch removed"`), fossil of a planned inter-app messaging system that was
designed, stubbed across 9+ apps, and decommissioned. willow-mcp has none of the
three.

The `*_schedule` tools (2.0) are not thin wrappers over `task_submit`.
`dream_schedule` calls `dream_state.queue_dream_task`, which runs
`dream_conditions` first and skips entirely if unmet. `intake_schedule` builds a
shell command (`promote_intake.py --days=... --agent=...`) then calls
`pg.submit_task()`. willow-mcp already has the generic primitive (`task_submit`,
`server.py:2036`); what it lacks are the opinionated, condition-gated facades.
The slice-backlog's earn-first items (`dream_*`, `wce_*`) are exactly these
facades.

The verify tools share a structural pattern but no schema. `ledger_verify` (2.0)
returns `{valid, broken_at, count}` (hash-chain walk). `source_trail_verify`
(2.0) returns `{claims, total, matched}`. `mem_check` (1.9 + 2.0) returns
`{flags, recommendation, evidence}`. willow-mcp's `frank_verify` mirrors
`ledger_verify`'s shape. All are read-only, `app_id`-first, returning a dict
with one boolean/enum outcome key plus evidence — but the key's *name* differs
per tool. No shared verdict schema exists to rely on programmatically.

### Apache-compatible alternatives by gap

**Threading.** [Monadical-SAS/zulip-mcp](https://github.com/Monadical-SAS/zulip-mcp)
(Apache-2.0) — 8 tools wrapping Zulip's native topic-threading. Different model
(stream + topic, not parent_id chains) but the best licence-clean reference for
a messaging MCP tool surface. No MCP server implements bespoke parent_id
reply-chains.

**Staged approval.** [Netflix Conductor](https://github.com/Netflix/conductor)
(Apache-2.0) — production-grade durable multi-state workflows with
pause/resume and human-task states. Could back a more complex approval graph than
the three-state machine. [Spring Statemachine](https://spring.io/projects/spring-statemachine)
(Apache-2.0) is the JVM design reference. No MCP server implements staged
approval.

**Block content.** [Editor.js](https://github.com/codex-team/editor.js)
(Apache-2.0) — document as ordered list of typed, addressable, independently
serialisable JSON blocks. Usable headless as a pure data model.

**Source verification.** [ClaimsMCP](https://github.com/AdamGustavsson/ClaimsMCP)
(Apache-2.0) — claim extraction from text, the preprocessing step of a verify
pipeline. [Loki / OpenFactVerification](https://github.com/Libr-AI/OpenFactVerification)
— full decompose → query → crawl → verify pipeline; licence unconfirmed.

**Governance ledger backing.** [immudb](https://github.com/codenotary/immudb)
(Apache-2.0) — embeddable tamper-proof, cryptographically verified history.
Lighter than [google/trillian](https://github.com/google/trillian) (Apache-2.0,
Merkle-tree log from Certificate Transparency) for the `frank_*` shape.

**Pagination and annotations.** Both are in the MCP spec itself. The MCP SDKs
(TypeScript/Python/C#, all MIT or Apache) implement pagination plumbing. Tool
annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint`) are self-reported hints, advisory-only. Extending pagination to
arbitrary tool results is an open discussion (issue #799).

### Shapes unique to willow-mcp (no external equivalent found)

Eight shapes nobody else builds:

1. **`gap_*` — self-observing backlog.** Records what the system doesn't know.
   Nearest hit: kakveda (licence unconfirmed), a failure-intelligence platform.
2. **`friction_scan`** — watches the KB's own edges for tension.
3. **`lineage_*` with "why"** — provenance chains that record reasoning.
4. **`frank_*` governance ledger** — tamper-evident append-only. immudb/Trillian
   could back the storage; the tool surface is unique.
5. **Dispatch federation** — cross-agent dispatch with depth limits, envelope
   gating, party ACLs.
6. **Nestor (tool routing)** — dynamic tool routing via agent registry
   permissions and the gate/manifest system.
7. **Nest intake pipeline** — household-context intake with guardian consent and
   subject-scoped tools.
8. **Egress gating** — integration-net manifests, consent checks, leased network
   access. No MCP server gates its own outbound calls.

### The verdict column, unpacked

**Build** (threading, draft/schedule, source verification): the prior art is
internal and the shape is domain-specific enough that no external library
matches. Re-land from 1.9/2.0 code when a consumer earns the surface.

**Adapt** (staged approval, block content): an Apache-2.0 library provides the
mechanism (Conductor, Editor.js), but none is MCP-aware — wrapping it into tools
is on us. Earn-first: the gap state machine already covers the current case.

**Spec** (pagination, annotations): no library needed; follow the protocol.
Pagination is a keyset cursor mapped to the SDK's opaque `cursor` / `nextCursor`
plumbing. Annotations are a mechanical sweep across ~110 `@mcp.tool()`
decorators, with 2.0's coverage as the reference.

### Integration stubs — compose, don't rebuild

willow-mcp declares six integration stubs (`integrations.py`): Gmail, Slack,
Notion, Google Drive, Datadog, Jira. All six have existing Apache-compatible MCP
servers, several official from the service provider:

| Stub | Best existing MCP server | Licence | Notes |
| --- | --- | --- | --- |
| Gmail | Google official Gmail MCP; taylorwilsdon/google_workspace_mcp | Apache-2.0; MIT | Workspace server covers Gmail + Drive + Calendar |
| Slack | Duolingo/slack-mcp; korotovsky/slack-mcp-server | Apache-2.0; MIT | Duolingo adds OAuth multi-user. 398 stars on korotovsky |
| Notion | makenotion/notion-mcp-server (official) | MIT | 4.6k stars. Notion shifting to hosted remote MCP |
| Google Drive | aaronsb/google-workspace-mcp; felores/gdrive-mcp-server | Apache-2.0; MIT | File CRUD, search, Sheets editing, permissions |
| Datadog | datadog-labs/mcp-server (official); dreamiurg/datadog-mcp | Apache-2.0; MIT | dreamiurg has 117 read-only tools |
| Jira | atlassian/atlassian-mcp-server (official) | Apache-2.0 | 4k stars. Covers Jira + Confluence + JSM + Bitbucket |

The composition answer: **delegate transport and API mechanics to these
existing servers; keep a thin willow-mcp adapter for egress gating and consent.**
The gateway ecosystem (MetaMCP, mcp-proxy) handles aggregation but lacks
first-class policy hooks — nothing supports `earned_by` predicates or
consent-checked outbound calls before forwarding. willow-mcp's egress gating
layer is the piece that cannot be composed away.

### MCP server testing and conformance

| Project | Licence | What it does |
| --- | --- | --- |
| [mcp-assert](https://github.com/blackwell-systems/mcp-assert) | MIT | Single Go binary, connects over real stdio/SSE/HTTP, runs full initialize handshake, calls tools with real arguments, asserts against 18 assertion types in YAML. Found 4,794 schema issues across 102 servers in a published scan |
| [agent-security-harness](https://github.com/marketplace/actions/agent-security-harness) | **Apache-2.0** | Security-focused MCP server testing, available as a GitHub Action |

The MCP Python and TypeScript SDKs (both MIT) ship `InMemoryTransport` /
`MockTransport` for zero-dependency unit tests. FastMCP's `Client` can connect
to a server in-process. For willow-mcp's ~110 tools, the combination of
SDK in-process transport (unit tests) + mcp-assert (conformance) +
agent-security-harness (security gate) covers the full test surface.

### Repos not yet surveyed

Seven MCP forks under `rudi193-cmd/` represent hands-on evaluation of external
prior art that the survey discusses generically: codebase-memory-mcp,
multimodels-mcp, mcp-memory-service, basic-memory, ctxvault, hermes-agent,
claudeclaw. All pushed July–August 2026. Linking which forks were examined to
which survey conclusions would strengthen provenance.

`Nestor` is now a standalone repo under active work (pushed same day as this
survey) — the survey names it as one of eight unique shapes but never examines
the implementation. `willow-gate`, `willow-config`, and `willow-compose` form an
uncovered infrastructure cluster: deployment, gating, and orchestration that the
MCP tools operate within.

## 2. MCP protocol features beyond tools

Surveyed 2026-08-18 against the 2026-07-28 MCP specification revision.
willow-mcp's surface is entirely tools today. The protocol offers more.

### Resources (adopt — high priority)

URI-addressable read-only data the server exposes via `resources/list` and
`resources/read`. Clients fetch them into context on demand. Servers can expose
concrete resources or parameterised URI templates (`kb://{collection}/{id}`)
following RFC 6570.

willow-mcp's KB atoms are a natural fit: each has a stable identity, is
read-only from the consumer's perspective, and benefits from URI-addressable
access. `resources/subscribe` (where supported) would let clients track changes.
The 2026-07-28 spec keeps resources as a first-class non-deprecated primitive.

Prior art: [knowledge-base-mcp-server](https://github.com/jeanibarz/knowledge-base-mcp-server)
exposes KB documents at `kb://<knowledge-base>/<path>` URIs — the closest
analogue. Licence unconfirmed; check before depending. The MCP SDKs (MIT) ship
all resource plumbing.

### Streamable HTTP transport (adopt — high priority)

The current recommended remote transport, replacing the deprecated HTTP+SSE.
Single HTTP endpoint for bidirectional communication, supports stateless
operation behind load balancers. The 2026-07-28 spec goes further: the protocol
core is now stateless (no `initialize` handshake, no `Mcp-Session-Id`), which
simplifies horizontal scaling.

willow-mcp is a remote server by nature. Any cross-call state should use
explicit, server-minted handles passed as tool arguments — which willow-mcp
already does with `app_id`.

| Project | Licence | Notes |
| --- | --- | --- |
| [achetronic/mcp-proxy](https://github.com/achetronic/mcp-proxy) | **Apache-2.0** (verified) | OAuth, JWT, transport bridging (Streamable HTTP ↔ stdio) |
| MCP Python SDK / TypeScript SDK | MIT | Ship Streamable HTTP server/client directly |
| [mcp-streamablehttp-proxy](https://pypi.org/project/mcp-streamablehttp-proxy/) | MIT | Python stdio-to-HTTP bridge |

### Server composition (watch — medium priority)

Aggregating multiple MCP servers behind a single endpoint.
[MetaMCP](https://github.com/metatool-ai/mcp-server-metamcp) (**Apache-2.0**,
verified, 2,200+ stars) is the leading aggregator: joins multiple downstream
servers with middleware for dynamic tool filtering, namespacing, and per-server
enable/disable.

willow-mcp should be composable *into* a gateway without surprises: no
protocol-level session assumptions, clean tool naming. The gateway pattern could
eventually subsume Nestor's bespoke routing if the generic tools mature.

### Prompts (maybe — low priority)

Server-defined prompt templates via `prompts/list` / `prompts/get`. Thin
adoption across the field — most popular servers expose zero prompts. Could
expose canned workflows ("summarise this collection", "audit provenance for
atom X") but trivial to add later.

### Deprecated features — do not adopt

**Sampling** (server-initiated LLM requests) — deprecated 2026-07-28 (SEP-2577).
Replacement: integrate directly with LLM provider APIs. The related
`InputRequiredResult` / MRTR pattern replaces it for mid-execution user input.

**Roots** (client-declared filesystem boundaries) — deprecated 2026-07-28.
Replacement: pass directories via tool parameters or server configuration.
Irrelevant to knowledge servers regardless.

**Built-in logging** (`notifications/message`) — deprecated 2026-07-28 in favour
of OpenTelemetry / stderr.

## 3. Observability for MCP servers

The 2026-07-28 MCP spec deprecated built-in `notifications/message` logging in
favour of OpenTelemetry. This is now the canonical observability path.

| Project | Licence | Notes |
| --- | --- | --- |
| [OpenTelemetry Python SDK](https://github.com/open-telemetry/opentelemetry-python) | **Apache-2.0** (verified) | The base instrumentation layer |
| [opentelemetry-instrumentation-mcp](https://pypi.org/project/opentelemetry-instrumentation-mcp/) | **Apache-2.0** | Auto-instruments Python MCP SDK: tool calls, spans, latency, errors |
| FastMCP (MIT) | MIT | Built-in OTel instrumentation for all MCP operations |
| [Sentry MCP integration](https://docs.sentry.io/) | BSD-3-Clause | Error tracking with MCP-aware context |

For willow-mcp's ~110 tools, the combination is: `opentelemetry-instrumentation-mcp`
for automatic span generation per tool call, the OTel Python SDK for export to
any backend (Jaeger, Grafana, Datadog), and stderr for operator-facing logs.
This replaces any custom logging willow-mcp currently does.

## 4. Rate limiting and backpressure

With ~110 tools and multi-tenant dispatch, rate limiting is structural, not
optional.

| Project | Licence | Notes |
| --- | --- | --- |
| [limits](https://github.com/alisaifee/limits) | MIT (verified) | Python, lightweight, multiple storage backends (Redis, memcached, in-memory). Used by Flask-Limiter. The most adoptable for a Python MCP server |
| [Gubernator](https://github.com/gubernator-io/gubernator) | **Apache-2.0** (verified) | Stateless distributed rate-limiting microservice from Mailgun. gRPC-native. For the case where willow-mcp scales horizontally |
| [Bucket4j](https://github.com/bucket4j/bucket4j) | **Apache-2.0** (verified) | Token-bucket algorithm, Java, distributed cache support. JVM only — design reference, not a direct dependency |

No MCP-specific rate-limiting middleware exists. The gap: rate limits per
`app_id` per tool, with backpressure signalled through the protocol (the MCP
spec does not define a rate-limit response shape — `isError: true` with a
`retry_after` is the best available convention).

## 5. Workflow and orchestration engines

§1 names Netflix Conductor for staged approval. The broader landscape for
dispatch/federation orchestration:

| Project | Licence | Notes |
| --- | --- | --- |
| [Netflix Conductor](https://github.com/Netflix/conductor) | **Apache-2.0** (verified) | Durable multi-state workflows, human-task states. Already in §1 |
| [Kestra](https://github.com/kestra-io/kestra) | **Apache-2.0** (verified) | Declarative YAML workflows, event-driven, stateless workers. 2.0 shipped 2026. The most actively maintained Apache-2.0 orchestrator |
| [Temporal](https://github.com/temporalio/temporal) | MIT (verified) | The reference durable-execution engine. Heavy, but the benchmark for reliability |
| [Restate](https://github.com/restatedev/restate) | MIT core | Lightweight durable execution, designed for resilient process orchestration |

willow-mcp's Kart task queue is the current orchestration layer. For anything
beyond single-step dispatch — multi-phase workflows, fan-out/fan-in, saga
compensation — Kestra (Apache-2.0, YAML-defined, event-driven) is the closest
architectural match.

## 6. Knowledge graph and embeddable stores

The KB tools need graph-shaped storage. The current backing is Postgres with
pgvector. Alternatives if the graph dimension grows:

| Project | Licence | Notes |
| --- | --- | --- |
| [Apache AGE](https://github.com/apache/age) | **Apache-2.0** (verified) | Postgres extension adding Cypher graph queries. Embeddable in the existing Postgres without a separate database. The lowest-friction path to graph queries over KB atoms |
| [TerminusDB](https://github.com/terminusdb/terminusdb) | **Apache-2.0** (verified) | Document store with graph traversal, versioned, Rust core. Fits the "provenance chains" requirement |
| [Qdrant](https://github.com/qdrant/qdrant) | **Apache-2.0** (verified) | Purpose-built vector similarity search. If pgvector's performance or feature set becomes a constraint |
| [LanceDB](https://github.com/lancedb/lancedb) | **Apache-2.0** (verified) | Embedded vector DB, zero infrastructure. Useful if willow-mcp ever runs without Postgres |
| [immudb](https://github.com/codenotary/immudb) | **Apache-2.0** (verified) | Already in §1 for governance; its verifiable-history model also backs KB provenance |

Apache AGE is the highest-leverage option: it adds `MATCH (a)-[:CITES]->(b)`
queries to the Postgres willow-mcp already uses, without a second database.
The `knowledge_edges` table and `lineage_*` tools would benefit directly.
