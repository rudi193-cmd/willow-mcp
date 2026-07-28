-- public.tasks — which shape is this database in?
--
-- Run this BEFORE either migration. It only reads. It exists because
-- `CREATE TABLE IF NOT EXISTS` decided this database's shape by boot order and
-- told nobody, so the first honest step is finding out what you actually have.
--
--   psql "$WILLOW_PG_DSN" -f docs/schema/migrations/tasks-preflight.sql

\pset border 2

SELECT
    CASE
        WHEN NOT EXISTS (SELECT 1 FROM information_schema.tables
                         WHERE table_schema = 'public' AND table_name = 'tasks')
            THEN 'ABSENT — create from docs/schema/tasks.postgres.sql'
        WHEN     EXISTS (SELECT 1 FROM information_schema.columns
                         WHERE table_schema='public' AND table_name='tasks' AND column_name='task_id')
         AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                         WHERE table_schema='public' AND table_name='tasks' AND column_name='id')
            THEN 'CANONICAL — willow-mcp shape, contract phase already done'
        WHEN     EXISTS (SELECT 1 FROM information_schema.columns
                         WHERE table_schema='public' AND table_name='tasks' AND column_name='task_id')
         AND     EXISTS (SELECT 1 FROM information_schema.columns
                         WHERE table_schema='public' AND table_name='tasks' AND column_name='id')
            THEN 'EXPANDED — both keys present, safe; run contract when readers have moved'
        WHEN EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_schema='public' AND table_name='tasks'
                       AND column_name='id' AND data_type = 'text')
            THEN 'LEGACY willow-2.0 (id text) — run the expand migration'
        WHEN EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_schema='public' AND table_name='tasks'
                       AND column_name='id' AND data_type = 'bigint')
            THEN 'LEGACY Grove (id bigint identity) — run the expand migration'
        ELSE 'UNKNOWN — not one of the three known shapes; inspect by hand'
    END AS shape;

-- Which canonical columns are missing, if any.
WITH canonical(col) AS (
    VALUES ('task_id'), ('task'), ('submitted_by'), ('network_authorization'),
           ('agent'), ('lane'), ('status'), ('result'), ('steps'),
           ('created_at'), ('completed_at'), ('claim_owner'), ('claimed_at'),
           ('attempts'), ('max_attempts'), ('retry_at'),
           ('submitter_run_id'), ('updated_at')
)
SELECT c.col AS missing_canonical_column
FROM canonical c
WHERE NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'tasks' AND column_name = c.col
)
ORDER BY 1;

-- Columns present that canonical does not define. `cmd` is Grove's display-only
-- column; the contract migration drops it once Grove reads `task` instead.
SELECT column_name AS non_canonical_column, data_type
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'tasks'
  AND column_name NOT IN (
      'task_id','task','submitted_by','network_authorization','agent','lane',
      'status','result','steps','created_at','completed_at','claim_owner',
      'claimed_at','attempts','max_attempts','retry_at','submitter_run_id','updated_at')
ORDER BY 1;

SELECT count(*) AS row_count FROM public.tasks;
