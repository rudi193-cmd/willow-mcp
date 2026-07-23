#!/usr/bin/env python3
"""provision_gate.py — grant a willow gate manifest the permission groups an
agent needs to run its own jobs through tools instead of by hand.

The gate manifest ($WILLOW_HOME/mcp_apps/<app>/manifest.json) is a live-env
file, not repo-tracked — so a hand-edit vanishes on container reclaim and the
next session's model re-derives the grant by hand. This script is the durable,
reproducible grant: it unions a documented permission set into the manifest,
and it FAILS LOUDLY if any requested group is not a real gate.PERMISSION_GROUPS
key (a silent no-op grant is exactly the "errors silently" failure mode we
outlawed).

The default grant is the "builder introspection + loop" set: the tool groups
that let an architect agent do — deterministically, without a model in the
loop — the jobs it was doing conversationally (code-graph coupling analysis,
receipts confirmation, context recovery, the gap/ouroboros loop, handoff
writing, nest doc review, lineage).

Usage:
  provision_gate.py [manifest.json]     # default: safe-app-store manifest
  provision_gate.py --print             # show the grant set and exit
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from willow_mcp import gate  # for the authoritative PERMISSION_GROUPS keys

# Groups that turn hand-run model jobs into tool calls. Each line is a job.
BUILDER_GRANT = [
    "store_read", "store_write",        # the shared memory
    "knowledge_read", "knowledge_write",# the KB
    "task_queue", "schema_admin",       # queue + schema mapping
    "gap_read", "gap_write", "gap_promote",   # the ouroboros loop end-to-end
    "code_graph_read", "code_graph_write",  # coupling map / impact — was grep+md5sum by hand
    "audit",                            # receipts_tail — loud confirmation of a write
    "context",                          # context_save/get — was re-reading the transcript
    "dispatch_write",                   # handoff_write_v4 / verify_handoff — was hand-written
    "nest_read",                        # nest digest/intake review — was in-process by hand
    "lineage_read",                     # provenance / "why this willow"
]

DEFAULT_MANIFEST = (
    Path(os.environ.get("WILLOW_HOME", Path.home() / ".willow"))
    / "mcp_apps" / "safe-app-store" / "manifest.json"
)


def _validate(perms):
    known = set(gate.PERMISSION_GROUPS)
    unknown = [p for p in perms if p not in known]
    if unknown:
        sys.stderr.write(
            "[provision_gate] REFUSING: not real permission groups: "
            f"{unknown}\n  (a grant that expands to nothing is a silent no-op)\n")
        sys.exit(2)


def provision(manifest_path: Path, grant) -> dict:
    _validate(grant)
    if not manifest_path.exists():
        sys.stderr.write(f"[provision_gate] manifest not found: {manifest_path}\n")
        sys.exit(2)
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    before = list(m.get("permissions", []))
    merged = list(dict.fromkeys(before + grant))  # union, order-stable
    added = [p for p in merged if p not in before]
    m["permissions"] = merged
    manifest_path.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    return {"manifest": str(manifest_path), "added": added,
            "already_had": before, "now": merged}


def main(argv):
    if "--print" in argv:
        _validate(BUILDER_GRANT)
        print("builder grant (all validated as real groups):")
        for g in BUILDER_GRANT:
            print(f"  {g:18} -> {sorted(gate.PERMISSION_GROUPS[g])}")
        return 0
    path = Path([a for a in argv if not a.startswith("-")][0]) if any(
        not a.startswith("-") for a in argv) else DEFAULT_MANIFEST
    result = provision(path, BUILDER_GRANT)
    print(json.dumps(result, indent=2))
    if not result["added"]:
        print("\n(already fully provisioned — nothing to add)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
