---
name: kart-tasks
description: Guided use of willow-mcp's Kart task queue — submit/poll, the task_net + allow_net network model and its footguns, and the worker-liveness caveat
---

# /kart-tasks

Walks through using willow-mcp's sandboxed task queue (`task_submit`,
`task_status`, `task_list`, `fleet_health`) correctly — including the two
things that most easily go wrong: **assuming a submitted task will run**, and
**mishandling the network permission**.

## When to use this

- You're about to submit shell work to Kart via `task_submit`.
- A task you submitted is stuck `pending` and you don't know why.
- You need a task to have network access and aren't sure how to grant it.

## 0. First, know this: submitting is not running

`task_submit` only inserts a `pending` row into the `tasks` table. Execution is
done by a **separate Kart worker** that polls the table and runs each task in a
bubblewrap sandbox. **If no worker is running, your task sits `pending`
forever** — `task_submit` returning `{"status": "pending"}` is *not* a signal
that anything will execute it.

> **Packaging caveat (current):** the Kart worker is being productionized into
> willow-mcp (see `docs/design/kart-productionization.md`). Until that lands, a
> clean `pip install willow-mcp` ships the queue tools but **not** the worker —
> task execution depends on a Kart worker being present and running on the host.
> The concrete `willow-mcp worker` run command will be documented here once the
> lift ships. Tracked as B-22 in `docs/BUGS.md`.

**Before trusting a submission, check the queue is actually being drained.**
Call `fleet_health` and read the counts: a healthy queue shows tasks moving
`pending → running → completed`. A large `pending` with `running: 0` and a
stale timestamp means nothing is listening — say so plainly rather than
polling `task_status` forever.

## 1. Submitting a task

```
task_submit(app_id=..., task="echo hello", agent="kart")
```

`task` is shell. Keep it a real command; the worker extracts and runs it in the
sandbox. Returns a `task_id` for polling.

## 2. The network model — and its footguns

Tasks run **network-isolated by default**. Egress is opt-in and gated:

- To run with network access, pass **`allow_net=True`**. This requires the
  **`task_net`** capability permission in the app's manifest. It is **not**
  included in `task_queue` or `full_access` — it must be granted explicitly
  (same separation as B-14/B-19). Without it, `allow_net=True` returns
  `net_denied` before anything is written.
- **Do not hand-embed `# allow_net` or `# allow_localhost` lines in `task`
  text.** The Kart worker reads its network policy from exactly those directive
  lines, so it's tempting to add one directly — but the server **strips any
  such caller-supplied line unconditionally** before storing the task (B-21 /
  L-NET-01). Embedding one does nothing except signal a misunderstanding of the
  gate. `# allow_net` can only enter the stored task through the
  permission-checked `allow_net=True` path; `# allow_localhost` cannot be
  self-granted at all. The PreToolUse hook warns if you try.

So: **network = `allow_net=True` + `task_net` in the manifest. Never a directive
in the task string.**

## 3. Polling

```
task_status(app_id=..., task_id=...)
```

Returns `status`, `result`, and completion time. Poll with restraint — if
`fleet_health` shows the queue isn't moving (see §0), stop and report the
worker gap rather than re-polling a task nothing will run.

## 4. Listing

`task_list` filters by status/agent; `fleet_health` gives the aggregate
counts. Use `fleet_health` first to distinguish "queued, worker will get to it"
from "queued, nothing is listening."

## What this skill will not do

It will not tell you to keep polling a `pending` task when `fleet_health` shows
no worker is draining the queue, and it will not add a `# allow_net` directive
to task text as a shortcut around the `task_net` permission — that path is
closed by design (B-21), and the correct move is to grant the permission.
