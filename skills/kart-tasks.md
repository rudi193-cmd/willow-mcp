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

Start one with:

```
willow-mcp worker --lane fast      # daemon: polls until stopped
willow-mcp worker --once           # drain whatever is queued, then exit
```

**Before trusting a submission, ask whether anything is draining the queue.**
You no longer have to guess. `fleet_health` reports live workers directly:

```json
{"pending": 3, "running": 0, ...,
 "workers": {"alive": 0, "workers": [...]},
 "stranded": true}
```

`stranded: true` means **there is pending work and no live worker** — the task
you just submitted will not run. Say that plainly instead of polling
`task_status` in a loop. `diagnostic_summary` raises the same condition as a
named `worker` problem with the fix attached.

Each entry in `workers.workers` carries a `state`:

| state | meaning |
|---|---|
| `alive` | process up, loop ticking — your task will be claimed |
| `stale` | process up, but its loop stopped ticking (wedged) |
| `dead` | the recorded pid is gone; a leftover file, not a worker |

Only `alive` counts. Heartbeats are **advisory telemetry, never authorization** —
no permission decision reads them.

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
`fleet_health` reports `stranded: true` (see §0), stop and report the worker
gap rather than re-polling a task nothing will run.

## 4. Listing

`task_list` filters by status/agent; `fleet_health` gives the aggregate counts
**plus worker liveness**. Check `stranded` first: it is exactly the distinction
between "queued, a worker will get to it" and "queued, nothing is listening."

## What this skill will not do

It will not tell you to keep polling a `pending` task when `fleet_health` reports
`stranded: true`, and it will not add a `# allow_net` directive to task text as a
shortcut around the `task_net` permission — that path is closed by design (B-21),
and the correct move is to grant the permission.
