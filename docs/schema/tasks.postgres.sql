-- willow-mcp — Kart task queue table (Postgres)
--
-- willow-mcp ADAPTS to an existing `tasks` table when one is present (see
-- docs/design/schema-adaptation.md); this DDL is for a fresh install that has
-- no such table yet. Columns match the canonical _TASK_FIELDS the server maps
-- (server.py: task_id, task, submitted_by, network_authorization, agent,
-- status, result, steps,
-- created_at, completed_at). After creating it, confirm the mapping once:
--   schema_confirm_mapping(app_id=..., table="tasks")
--
-- The worker (kartikeya, via WillowMcpTaskQueue) claims pending rows for its
-- agent with FOR UPDATE SKIP LOCKED and writes status/result/completed_at.

CREATE TABLE IF NOT EXISTS tasks (
    task_id       text PRIMARY KEY,
    task          text NOT NULL,
    submitted_by  text NOT NULL DEFAULT '',
    network_authorization text NOT NULL DEFAULT '',
    agent         text NOT NULL DEFAULT 'kart',
    status        text NOT NULL DEFAULT 'pending',   -- pending | running | completed | failed
    result        jsonb,
    steps         integer,
    created_at    timestamptz NOT NULL DEFAULT now(),
    completed_at  timestamptz
);

-- Claim path: WHERE status='pending' AND agent=? ORDER BY created_at.
CREATE INDEX IF NOT EXISTS idx_tasks_claim ON tasks (status, agent, created_at);

-- Optional: self-populate completed_at when a row reaches a terminal state
-- (mirrors the trigger B-17 added to the shared fleet DB). Safe to skip if the
-- worker always sets completed_at explicitly (it does via mark_done).
CREATE OR REPLACE FUNCTION set_task_completed_at() RETURNS trigger AS $$
BEGIN
  IF NEW.status IN ('completed', 'failed') AND NEW.completed_at IS NULL
     AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM NEW.status) THEN
    NEW.completed_at := now();
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_task_completed_at ON tasks;
CREATE TRIGGER trg_task_completed_at BEFORE INSERT OR UPDATE ON tasks
  FOR EACH ROW EXECUTE FUNCTION set_task_completed_at();
