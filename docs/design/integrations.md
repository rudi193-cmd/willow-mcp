# Integrations — earned surface, declared stubs

*Status: **LOCKED** rule, living ledger — 2026-07-09*

## 1. Provenance

This design was mined from an over-scoped monorepo sketch ("enterprise-mcp-fabric"):
fifty vendor adapters, seven apps, three message buses, k8s/helm/terraform — none
of it built, all of it empty stubs on day one. The sketch was discarded; three
ideas survived the mining:

1. **A shared adapter base** — auth, retry, rate handling, bounded transport as
   common plumbing (`adapters/base/` in the sketch → `BaseAdapter` in
   `integrations.py`).
2. **A registry** — adapters as first-class, enumerable entries rather than
   ad-hoc code (`integration_list`).
3. **The named integration points themselves** — as a *menu*, not a commitment.

Everything else in the sketch was surface declared in advance of need, which is
the exact anti-pattern this repo's culture exists to prevent.

## 2. The earn rule

> **An adapter is implemented when work in this fleet needs it twice.**
> Until then it may exist only as a *declared stub*.

A declared stub:

- is registered and listable (`integration_list` shows the ledger);
- **fails closed** — calling it returns `not_implemented`, never a partial or
  fake result, and never opens a socket;
- names **`needs`** (what is technically missing — usually an auth flow or a
  config decision) and **`earned_by`** (the concrete fleet event that justifies
  building it).

The "twice" is deliberate: the first need is an experiment, the second is a
pattern. One-off needs are served by `task_submit` with an egress lease — the
sandbox lane exists precisely so the server does not grow adapters for errands.

A stub with an empty `needs` or `earned_by` fails the test suite
(`test_every_stub_declares_needs_and_earned_by`). A stub that is never going to
be earned should be deleted from the registry, not left to imply intent.

## 3. Current ledger

| Adapter | Status | Earned by |
|---|---|---|
| `github` | **live** | this repo's own fleet lives on GitHub |
| `huggingface` | **live** | the fleet's local-model work reads Hub metadata |
| `gmail` | stub | a fleet task that must read or send mail twice |
| `slack` | stub | a dispatch consumer that reports into Slack twice |
| `notion` | stub | a knowledge-sync task targeting Notion twice |
| `google-drive` | stub | a fleet task that must fetch or store Drive files twice |
| `datadog` | stub | `fleet_health` having an external consumer twice |
| `jira` | stub | a task-queue sync request against a real Jira site twice |

Anything from the original sketch not in this table (salesforce, snowflake,
whatsapp, tuya, …) is not even a stub. The menu is not the ledger.

## 4. Egress: the fourth consumer of the three-key gate

`integration_call` makes the **server process** an egress actor — a different
lane than the Kart sandbox, and a strictly more privileged one (server uid,
full filesystem view, no network namespace). It therefore gets its **own
capability line**:

| Key | Question | Same as task lane? |
|---|---|---|
| `integration_net` | may this app ever call out via adapters? | **no** — own line (B-19: egress is never inherited across lanes) |
| `consent.internet` | is egress permitted right now, fleet-wide? | yes — one switch stops both lanes |
| egress lease | this app, until when? | yes — one lease, `willow-mcp grant-net` |

`task_net` never implies `integration_net`, and neither is in `full_access`.
`integration_call` (the tool itself) is *also* excluded from `full_access`, so
even the attempt surface is opt-in — a broad grant must never silently carry
the ability to knock on the egress gate.

`WILLOW_MCP_STRICT_TRUST_ROOT` applies unchanged: when the process can write
the keys that authorize it and strict mode is on, integration egress is refused
exactly as task egress is. The B-32 residual is shared by both lanes; it is not
re-litigated here.

## 5. Credentials

Env var first (operator export beats stored state), then vault under
`integration/<name>/token`. `willow-mcp-integrations set-token <name>` writes
the vault entry via a hidden prompt — never argv, which lands in shell history
and the process table. No tool, ledger row, log line, or error detail ever
carries a credential; `credential_source()` reports where one came from
(`env:VAR` / `vault` / none), and transport error bodies are scrubbed of the
token before they leave the module.

## 6. Bringing a stub live — checklist

1. The earn condition in the ledger has actually occurred, twice. Cite both.
2. Resolve what `needs` names (auth flow, config decision) — as its own PR if
   it is an auth *flow* (OAuth2 refresh tokens are shared work: gmail and
   google-drive, for instance, ride the same flow).
3. Convert the class from `StubAdapter` to `BaseAdapter`, set `env_vars`,
   `credential_required`, and any API-version headers.
4. Tests: credential resolution, one mocked happy path, one mocked failure
   path. The shared transport is already covered — do not re-test retries.
5. Update the ledger table above and the stub counts in
   `tests/test_integrations.py::test_registry_lists_live_and_stub_adapters`.
6. The three-key gate needs **no** per-adapter work — that is the point of it.
