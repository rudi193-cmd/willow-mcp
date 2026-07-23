---
kind: "doc"
name: "ui-concept-sketches-a-tree-two-audiences"
description: "Two self-contained HTML mockups exploring what a client UI for willow-mcp could look like — unwired design sketches, not a build."
---

@markdownai v1.0

# UI concept sketches — a tree, two audiences

Two self-contained HTML mockups exploring what a client UI for willow-mcp
could look like. No build step, no dependencies — open either file directly
in a browser. Design sketches, not a build: nothing here is wired to a real
`willow-mcp` instance.

Both are grown from the same idea: the gate in this codebase is already
named "sap" (`gate.NET_PERMISSION`, the `# allow_net` directive). So the
whole tool surface is read as a tree — trunk = overall health, sap = the
task queue in motion (or not), canopy = the agent fleet, roots/leaves =
persistent memory, litter = the activity/receipt log. Built design-first:
the metaphor and the visual language were settled before any TUI layout was
fit to it, rather than starting from an existing terminal UI and skinning it
after the fact.

## `willow-dev-tui.html` — developer-facing

True-black terminal palette. A k9s-style TUI mockup (CSS-bordered panes, not
hand-aligned ASCII, so nothing misaligns) alongside its browser "mirror" —
the same data as web cards, an SVG ring diagram for schema-mapping state, a
sap-flow gauge that visually shows the queue as stalled when no Kart worker
is running. Two easter eggs: type `sap` anywhere on the page (unstalls the
gauge for a few seconds), and triple-click the trunk in the hero art (it
reports the real historical failed-task count).

Assumes the viewer already knows what MCP/Postgres/a task queue are — labels
use the real tool/table vocabulary (`fleet_status`, `schema_confirm_mapping`,
`receipts_tail`, etc).

A seventh tree part, **stomata**, was added once the egress gate got its own
CLI (`willow-mcp gates`): the pores that decide whether an app may exchange
anything with the outside world — `consent.internet` (the operator's standing
switch), `task_net` (the capability to ever ask), and the egress lease (the
time-boxed grant), all three or the pore stays shut. Unlike every other part
of the tree here, this one isn't a fabricated mockup number: `willow-mcp
gates` renders this exact three-key on/off state today. The mirror's Stomata
card is deliberately built from the same primitives (`chip`/`agent-row`)
already in the file rather than new CSS, to keep it feeling native to the
sketch instead of bolted on.

## `willow-general-audience.html` — consumer-facing

Same tree, no terminal, no jargon. Every label is something a person would
actually say: "Your helpers" instead of `fleet_status`, "What Willow's doing
for you" instead of the task queue, "What Willow remembers" instead of
knowledge/store, raw IDs and error strings translated into plain sentences.
Daylight palette by default with a proper dark-mode variant (follows
`prefers-color-scheme`, unlike the dev version's deliberate dark-only
terminal identity). Schema-mapping ("rings") was dropped entirely here —
it has no honest translation for someone who doesn't know what a database
migration is. Easter egg: tap the tree three times.

## Using these

Neither file is a spec — they're a starting point for whichever direction a
real client UI takes: pick a palette/type system from one, borrow the
plain-language translation table from the other, or use the tree metaphor as
a north star for whatever information architecture a real build settles on.
