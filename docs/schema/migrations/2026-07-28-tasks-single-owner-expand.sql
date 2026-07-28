-- public.tasks — single owner, EXPAND phase
--
-- Three repos each shipped `CREATE TABLE IF NOT EXISTS tasks` for the same
-- unqualified name, with three different primary keys:
--
--   willow-2.0  core/pg_bridge.py:118   id      TEXT PRIMARY KEY
--   Grove       schema.sql              id      BIGINT GENERATED ALWAYS AS IDENTITY
--   willow-mcp  docs/schema/tasks.postgres.sql
--                                       task_id text PRIMARY KEY
--
-- `IF NOT EXISTS` means the second and third creators silently no-op, so which
-- shape a database ends up with is decided by boot order and nothing reports it.
-- willow-mcp already tolerates this by introspecting (docs/design/schema-
-- adaptation.md); the other two assert their shape and get whatever they get.
--
-- This migration makes willow-mcp's shape canonical. It is the EXPAND half of
-- expand-migrate-contract: it only ADDS. A single-step rename of `id` to
-- `task_id` would break whichever consumer deployed second, so `id` stays until
-- every reader has moved (the CONTRACT migration, run separately and later).
--
-- Idempotent: safe to run repeatedly, and on a database already canonical.
-- Transactional: either the whole expand lands or none of it does.
--
-- APPLY: operator-run, once per database, after taking a backup.
--   psql "$WILLOW_PG_DSN" -f docs/schema/migrations/2026-07-28-tasks-single-owner-expand.sql
--
-- VERIFY FIRST: docs/schema/migrations/tasks-preflight.sql reports which of the
-- three shapes a live database currently has. Run it before this.

BEGIN;

-- Refuse on a table this migration was not written for, rather than half-migrate
-- it. A `tasks` table with none of the three known primary keys is somebody
-- else's table and must be looked at by a human first.
DO $$
DECLARE
    has_tasks   boolean;
    has_id      boolean;
    has_task_id boolean;
BEGIN
    SELECT EXISTS (SELECT 1 FROM information_schema.tables
                   WHERE table_schema = 'public' AND table_name = 'tasks')
      INTO has_tasks;
    IF NOT has_tasks THEN
        RAISE EXCEPTION 'public.tasks does not exist — create it from '
                        'docs/schema/tasks.postgres.sql instead of migrating';
    END IF;

    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'tasks'
                     AND column_name = 'id') INTO has_id;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'tasks'
                     AND column_name = 'task_id') INTO has_task_id;

    IF NOT has_id AND NOT has_task_id THEN
        RAISE EXCEPTION 'public.tasks has neither `id` nor `task_id` — this is '
                        'not one of the three known shapes; inspect it by hand';
    END IF;
END $$;

-- ── The canonical key ────────────────────────────────────────────────────────
-- Added as a plain nullable column first, then populated, then constrained.
-- `id::text` covers both legacy shapes: willow-2.0's TEXT passes through, and
-- Grove's BIGINT identity becomes its own decimal string. That is lossless and
-- reversible — the CONTRACT migration keeps a copy before dropping `id`.
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS task_id text;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'tasks'
                 AND column_name = 'id') THEN
        UPDATE public.tasks SET task_id = id::text WHERE task_id IS NULL;
    END IF;
END $$;

-- ── Canonical columns that a legacy shape may lack ───────────────────────────
-- Every one is additive with a default, so existing rows stay valid and existing
-- INSERTs that omit them keep working.
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS task             text;
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS submitted_by     text NOT NULL DEFAULT '';
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS network_authorization text NOT NULL DEFAULT '';
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS agent            text NOT NULL DEFAULT 'kart';
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS lane             text NOT NULL DEFAULT 'fast';
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS status           text NOT NULL DEFAULT 'pending';
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS result           jsonb;
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS steps            integer;
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS created_at       timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS completed_at     timestamptz;
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS claim_owner      text;
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS claimed_at       timestamptz;
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS attempts         integer NOT NULL DEFAULT 0;
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS max_attempts     integer NOT NULL DEFAULT 3;
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS retry_at         timestamptz;
-- Absorbed from willow-2.0 rather than dropped: that repo's queue still writes
-- both, and canonical carrying them is what lets this be a rename rather than
-- a data loss.
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS submitter_run_id text;
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS updated_at       timestamptz NOT NULL DEFAULT now();

-- ── Constrain the canonical key ──────────────────────────────────────────────
-- NOT NULL only once every row is populated; a UNIQUE index rather than a
-- PRIMARY KEY because `id` still holds that until the contract phase.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.tasks WHERE task_id IS NULL) THEN
        RAISE EXCEPTION 'task_id could not be populated for every row — refusing '
                        'to constrain it; inspect public.tasks by hand';
    END IF;
END $$;

ALTER TABLE public.tasks ALTER COLUMN task_id SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS tasks_task_id_key ON public.tasks (task_id);

-- Claim path, same as the canonical DDL ships.
CREATE INDEX IF NOT EXISTS idx_tasks_claim
    ON public.tasks (status, agent, lane, retry_at, created_at);

COMMIT;
