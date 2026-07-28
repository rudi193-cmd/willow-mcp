-- public.tasks — single owner, CONTRACT phase
--
-- DESTRUCTIVE. Run only when EVERY reader and writer of public.tasks has moved
-- to the canonical column names. Until then the expand phase is a complete,
-- safe resting state and there is no hurry to run this.
--
-- Preconditions, in order:
--   1. The expand migration has run (tasks-preflight.sql reports EXPANDED).
--   2. willow-2.0 no longer writes `id` / no longer creates this table.
--   3. Grove reads `task_id` and `task` rather than `id` and `cmd`.
--   4. You have a backup.
--
-- What it does: preserves the legacy key as `legacy_id`, drops `id`, promotes
-- `task_id` to PRIMARY KEY, and drops Grove's display-only `cmd`.
--
-- `legacy_id` is kept deliberately rather than dropped. The expand phase mapped
-- Grove's BIGINT to its decimal string, which is reversible only while the
-- original is still there — and anything outside these three repos that recorded
-- a task id (a log line, a handoff note, an external ticket) refers to the old
-- value. Dropping it is a separate, later decision that needs its own evidence.
--
-- APPLY:
--   psql "$WILLOW_PG_DSN" -f docs/schema/migrations/2026-07-28-tasks-single-owner-contract.sql

BEGIN;

DO $$
DECLARE
    has_id      boolean;
    has_task_id boolean;
    unpopulated bigint;
BEGIN
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='tasks' AND column_name='id')
      INTO has_id;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='tasks' AND column_name='task_id')
      INTO has_task_id;

    IF NOT has_task_id THEN
        RAISE EXCEPTION 'task_id is absent — run the expand migration first';
    END IF;

    IF NOT has_id THEN
        RAISE NOTICE 'public.tasks is already contracted — nothing to do';
        RETURN;
    END IF;

    -- Never drop a key while any row would lose its identity.
    SELECT count(*) FROM public.tasks WHERE task_id IS NULL INTO unpopulated;
    IF unpopulated > 0 THEN
        RAISE EXCEPTION 'task_id is NULL on % row(s) — refusing to drop `id`', unpopulated;
    END IF;
END $$;

-- Preserve the legacy key under a name nothing queries, then drop the original.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='tasks' AND column_name='id') THEN
        ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS legacy_id text;
        UPDATE public.tasks SET legacy_id = id::text WHERE legacy_id IS NULL;
        ALTER TABLE public.tasks DROP CONSTRAINT IF EXISTS tasks_pkey;
        ALTER TABLE public.tasks DROP COLUMN id;
    END IF;
END $$;

-- Promote the canonical key. The unique index from the expand phase is dropped
-- first so the PRIMARY KEY can build its own without colliding on the name.
-- Guarded: `ADD PRIMARY KEY` is not idempotent — a second run raises "multiple
-- primary keys for table tasks are not allowed", which would abort a rerun that
-- otherwise has nothing left to do.
DROP INDEX IF EXISTS tasks_task_id_key;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_index
                   WHERE indrelid = 'public.tasks'::regclass AND indisprimary) THEN
        ALTER TABLE public.tasks ADD PRIMARY KEY (task_id);
    END IF;
END $$;

-- Grove's display-only column. It rendered a truncated "Command"; the canonical
-- `task` carries the same content, and Grove reads that as of the consumer change
-- this phase is gated on.
ALTER TABLE public.tasks DROP COLUMN IF EXISTS cmd;

COMMIT;
