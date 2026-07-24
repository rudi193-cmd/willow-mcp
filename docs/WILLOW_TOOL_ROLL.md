# The Willow Tool Roll — moved

The tool roll now lives in its correct home: the **Willow Technical Manual**,
whose workshop tab mirrors Martin "Sticky" Round's *Complete Spanner's Manual for
Lambretta* — the right genre for a grease-and-torque treatment of the stack.

**Repo:** `rudi193-cmd/willow-tech-manual` → `docs/workshop/`

| Chapter | Covers |
|---|---|
| `01-tools-for-the-job` | The bench roll (cold-start reconstruction) and the ride roll (live-session seal/verify); bench discipline — route around the structural gates, inspect the welds, mock before commit |
| `02-scooter-use-and-maintenance` | Walk-around, scheduled levels, the quarterly restore drill |
| `03-fault-diagnosis` | Env-less boot (`verdict=broken` → reconnect); deny-vs-defect |
| `appendix-c-torque-settings` | `[MEASURE]` over guessed numbers; retry backoff 2/4/8/16s |
| `appendix-d-jetting-standard-machines` | Stock baseline (consent all-off) vs rejetting for a tuned build |

The reusable scripts referenced there (reconstruction recipe, seal/verify
tooling) still live only in ephemeral `/workspace` and have not yet been
relocated — see the manual's `01-tools-for-the-job` for what they are and where
they belong (`sean-data-vault/scripts/` for the bench roll, this repo's
`scripts/` for the ride roll).
