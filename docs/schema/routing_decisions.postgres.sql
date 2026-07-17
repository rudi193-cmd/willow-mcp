-- willow-mcp — routing decision ledger (Postgres)
--
-- Backs `agent_route` and `agent_dispatch_result`. This DDL is for a fresh
-- install; on a shared fleet DB the table already exists.
--
-- Write path:
--   agent_route            INSERT (id, prompt_hash, session_id, rule_id,
--                                  confidence, decision, kind='agent_route')
--   agent_dispatch_result  UPDATE decision = decision || %s::jsonb  WHERE id=?
--
-- `decision` MUST be jsonb — agent_dispatch_result concatenates the result
-- payload onto it with the `||` jsonb operator; a text column would break that
-- update. `session_id` carries the caller's app_id, `rule_id` the target agent,
-- and `confidence` the routing score (agent_route writes 1.0). Unlike
-- `knowledge`/`tasks` there is no schema_confirm_mapping step — the columns are
-- referenced by fixed name, not through a schema-adapted mapping.

CREATE TABLE IF NOT EXISTS routing_decisions (
    id          text        PRIMARY KEY,
    prompt_hash text,
    session_id  text,
    rule_id     text,
    confidence  real,
    decision    jsonb       NOT NULL DEFAULT '{}'::jsonb,
    kind        text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
