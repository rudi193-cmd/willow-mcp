# Project collection alias migration inventory

Work order C303AA2F adds explicit logical aliases; it does not rename directories
or synthesize records.

## Inventory (2026-07-16)

Read-only SOIL probes were made for:

- `projects_willow_stack`
- `projects_willow_pm_portfolio`
- `projects_willow_pm_milestones`
- `projects_willow_pa_commitments`
- `projects_willow_governance_flags`
- `projects_willow_orient`

No records were returned to the `hanuman` scope. This is an inventory result,
not evidence that another store root or identity has no records.

## Archive-first procedure

1. Run `store_list` against each declared physical target under the Willow
   manifest and record IDs/counts.
2. Inventory any operator-declared legacy source by its exact physical name.
   Never derive a source by replacing `/` characters.
3. Copy each source record byte-for-byte to an operator-named archive collection,
   adding only provenance metadata (`source_collection`, `source_id`,
   `archived_at`). Do not delete or mutate the source.
4. Copy into the canonical target only after ID/content collision review. Preserve
   the original ID when free; on collision, stop for operator resolution.
5. Re-run counts and content hashes. Alias enablement is independent of record
   migration, so rollback means removing the manifest alias, not deleting data.
