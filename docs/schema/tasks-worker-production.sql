-- DD0114E5 reviewed forward migration for production worker claims.
--
-- Apply deliberately, then reconfirm the `tasks` schema mapping. The service
-- installer does not mutate Postgres and no server startup path applies this.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS lane text NOT NULL DEFAULT 'fast';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS claim_owner text;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS claimed_at timestamptz;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 3;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retry_at timestamptz;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_at timestamptz;

ALTER TABLE tasks
    DROP CONSTRAINT IF EXISTS tasks_lane_check;
ALTER TABLE tasks
    ADD CONSTRAINT tasks_lane_check CHECK (lane IN ('fast', 'batch'));

DROP INDEX IF EXISTS idx_tasks_claim;
CREATE INDEX idx_tasks_claim
    ON tasks (status, agent, lane, retry_at, created_at);
