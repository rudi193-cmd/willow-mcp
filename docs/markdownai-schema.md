# MarkdownAI (mai) — document schema

The canonical shape of a **proper `@markdownai` document** and the directive
grammar the mai tools resolve. Grounded in the parser
(`src/willow_mcp/mai/parser.py`, which is authoritative — where this doc and
the code disagree, the code wins) and aligned to the templates already in
willow-mcp: the skills (`skills/*.md`), and `ASSIGNMENT` / `CLOSEOUT`
(`docs/templates/`, `src/willow_mcp/bundle/templates/`).

Machine-checkable frontmatter schema: [`docs/schema/markdownai.schema.json`](schema/markdownai.schema.json).
Tools: the ten `mai_*` tools (opt-in via `WILLOW_MCP_MARKDOWNAI=1`).

---

## 1. Document envelope

A proper mai document has, in this order:

```
---                     ← optional YAML frontmatter (0 or 1 block)
name: coordinator
description: …
---

@markdownai v1.0        ← REQUIRED header, first non-blank line of the body
                          version token matches v<digits>[.<digits>…]
# Title …               ← markdown body, may contain @directives
```

**Ordering rule (load-bearing).** The `@markdownai` header must be the first
non-blank line **of the body** — i.e. *after* the YAML frontmatter, never
before it. `@markdownai` on line 1 with frontmatter beneath it is malformed
and detection fails (this was a real fleet bug: a sync tool that emitted the
header before YAML). The parser strips one leading `---…---` block, then
requires the body to start with `@markdownai`.

A file is treated as a mai document iff it is a `.md` file whose body (after
optional frontmatter) begins with `@markdownai`. Anything else is returned
verbatim by `mai_read_file` — the tools never rewrite non-mai markdown.

---

## 2. Frontmatter schema

Frontmatter is optional YAML. When present it is validated by
[`markdownai.schema.json`](schema/markdownai.schema.json). Field sets are
per **kind** (an optional `kind:` discriminator selects the strict shape;
without it, frontmatter is permissive/extensible):

| kind | required | optional | matches |
|------|----------|----------|---------|
| `skill` / `command` | `name`, `description` | `argument-hint`, `b17`, … | `skills/*.md` |
| `assignment` | `title`, `from`, `to`, `dispatch_id` | `role`, `priority` (`high`\|`normal`\|`low`), `reply_to` | `ASSIGNMENT.template.md` |
| `closeout` | `dispatch_id`, `from`, `to` | `date`, `role`, `b17` | `CLOSEOUT.template.md`, and the tool-emitted `closeout.md` |

`additionalProperties` is allowed everywhere — the schema pins the known fields
and enums without freezing the frontmatter. Skills in this repo already carry
`name`/`description`; they become *proper* mai docs by adding the
`@markdownai v1.0` header line after the frontmatter.

**The closeout is tool-emitted.** `closeout.md` is not hand-written — the
`handoff_write_v4` MCP tool renders it from a structured
`handoff.json` (`handoff_v1`) it writes under
`$WILLOW_HOME/dispatch/{dispatch_id}/`. That JSON is the source of truth, and
its `**From:** / **To:** / **Date:**` map to `app_id` / `reply_to` /
`written_at`; the findings become the `## Findings` table. Its contract has its
own schema: [`docs/schema/handoff.schema.json`](schema/handoff.schema.json).
Note the tool's `closeout.md` does **not** yet carry an `@markdownai` header —
so it is a rendered dispatch artifact, not a mai document today; emitting the
header (and a `kind: closeout` frontmatter block) from the tool is what would
make it proper mai.

---

## 3. Directive grammar

Directives are lines/blocks beginning with `@`. Every directive the parser
resolves, with its render behavior:

### Data & environment

| Directive | Syntax | Renders to |
|-----------|--------|-----------|
| `@env` | `@env key=NAME fallback=…` (or `@env NAME`) | the env var's value, or the fallback |
| `@connect` | `@connect NAME type=postgres uri=env.WILLOW_PG_URI` | nothing (registers a named connection; `env.X` resolves from the environment) |
| `@db` | `@db using="NAME" raw="SQL" on-error=""` | JSON rows; `on-error` is returned verbatim on failure. Defaults to `dbname=$WILLOW_PG_DB user=$WILLOW_PG_USER` when no connection is registered |
| `@db … \| @render` | `@db … \| @render type=table` | a markdown table (`type=table`) or pretty JSON (`type=json`, default) of the rows |
| `@http` | `@http url=… ` (or `src=…`, `env.X` allowed) | the response, JSON-parsed when possible; `{ "error": … }` on failure |

`@db` and `@http` results are cached by directive; `mai_invalidate_cache`
clears them. `@db` uses `psycopg2` (already a willow-mcp dependency).

### Structure & flow

| Directive | Syntax | Meaning |
|-----------|--------|---------|
| `@phase` | `@phase NAME` … (until next `@phase` or EOF) | a named section; `mai_list_phases` / `mai_resolve_phase` / `mai_next_phase` walk them; `mai_read_file(phase=NAME)` renders just one |
| `@macro` / `@endmacro` | `@macro NAME … @endmacro` | a reusable template; **removed** from rendered output; invoked with `mai_call_macro(macro=NAME, args={…})`, substituting `{k}` and `$k` |
| `@constraint` | `@constraint severity=critical … ` (until next `@constraint` or EOF) | a rule; `mai_get_constraints` returns them sorted `critical` > `error` > `warning` > `info` |
| `@prompt` / `@end` | `@prompt … @end` | instructions for the AI reader; **removed** from rendered output |
| `@if` / `@endif` | `@if consumer="ai" … @endif` | kept when `consumer` matches (or is unset), else stripped |
| `@define-concept` | reserved | not yet resolved — stripped as an unknown directive |

### Substitution (skills)

- `$ARGUMENTS` ← `mai_read_file(skill_args=…)`
- `${NAME}` / `$NAME` (uppercased) ← `mai_read_file(skill_named_args={name: …})`
- Fill-in templates (ASSIGNMENT/CLOSEOUT) use human `{placeholder}` markers —
  these are **not** mai substitutions; they are filled by the orchestrator
  writing the document. Use `${VAR}` only when you want mai to substitute.

Any unrecognized `@directive` line is treated as non-content and stripped in
the render.

**Authoring rules the parser enforces by shape (verified against the tools):**

- **`@constraint` captures greedily** — a constraint's body runs until the
  *next* `@constraint` or end-of-document. Put constraints **together**, and
  keep body content (phases, prose) *above* them, or the last constraint will
  swallow everything after it into its `text`. (Same for the block forms:
  `@macro…@endmacro`, `@prompt…@end`, `@if…@endif` must be closed.)
- **The header is exact** — `@markdownai v<n>[.<n>…]` as the first body line.
- **One frontmatter block**, fenced by `---`, and only before the header.

---

## 4. Render modes

`mai_read_file(format=…)`:

- **`ai`** (default) — token-efficient: header stripped, `@connect`/`@macro`/
  `@prompt` blocks removed, `@if` applied, `@env`/`@db`/`@http` resolved,
  unknown directives stripped, trailing whitespace trimmed, runs of blank
  lines collapsed to one.
- **`standard`** — same resolution, full whitespace preserved.

Both resolve directives; the difference is only condensation.

---

## 5. Tool surface

| Tool | Schema element it operates on |
|------|-------------------------------|
| `mai_read_file` | whole document → rendered body (§4) |
| `mai_write_file` | whole document (guards the `@markdownai` header on existing mai files) |
| `mai_list_phases` / `mai_resolve_phase` / `mai_next_phase` | `@phase` (§3) |
| `mai_call_macro` | `@macro` (§3) |
| `mai_get_constraints` | `@constraint` (§3) |
| `mai_get_env` | environment (backs `@env`) |
| `mai_execute_directive` | a single `@env` / `@db` / `@http` string |
| `mai_invalidate_cache` | the `@db`/`@http` result cache |

---

## 6. Conformance — the existing templates as proper mai

### Skill (already has frontmatter; add the header)

```markdown
---
name: coordinator
description: Coordinator mode — fan-out tasks to sub-agents.
---

@markdownai v1.0

## When to use
@if consumer="ai"
Condensed guidance for the agent reader.
@endif

@constraint severity=critical
Never dispatch without a fork_create first.
```

### Assignment (fill-in fields lifted into frontmatter)

```markdown
---
kind: assignment
title: Scrub the law-gazelle manifest
from: vishwakarma
to: hanuman
role: builder
priority: high
dispatch_id: D-2026-07-23-001
reply_to: "#fleet"
---

@markdownai v1.0

## Bite
One sentence — the single outcome.

@constraint severity=error
Out of scope: do not touch data outside git.
```

### Closeout (as the handoff tool could emit it)

`handoff_write_v4` renders `closeout.md` from `handoff.json`. A *proper-mai*
closeout would carry the header + `kind: closeout` frontmatter, and the
findings table can be produced by mai from a `@db` query instead of being
string-built — so the closeout renders live rather than being frozen at write
time:

```markdown
---
kind: closeout
dispatch_id: D-2026-07-23-001
date: 2026-07-23
from: hanuman
to: vishwakarma
---

@markdownai v1.0

## What was done
Scrubbed the manifest; verified no case numbers remain.

## Findings
@db using="willow" raw="SELECT id, text, severity FROM findings WHERE dispatch_id='D-2026-07-23-001'" | @render type=table
```

The structured `handoff.json` behind it validates against
[`handoff.schema.json`](schema/handoff.schema.json).

The current `ASSIGNMENT`/`CLOSEOUT` **template files** use `{placeholder}`
body fields and no header — valid markdown, but not yet mai. Upgrading the
templates (fields → frontmatter, add the header) and teaching
`handoff_write_v4` to emit the header are mechanical lifts, tracked separately
so this schema can land first.

---

## 7. Validate

Frontmatter, against the JSON Schema:

```python
import json, jsonschema, yaml   # yaml only to read the block
schema = json.load(open("docs/schema/markdownai.schema.json"))
jsonschema.validate(frontmatter_dict, schema)
```

Body, against the live grammar — round-trip through the tools with
`WILLOW_MCP_MARKDOWNAI=1`:

```
mai_read_file(path=…)            # renders per §4
mai_get_constraints(file=…)      # @constraint, severity-sorted
mai_list_phases(file=…)          # @phase
```

ΔΣ=42
