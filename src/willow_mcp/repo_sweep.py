"""Read-only hygiene sweep across every git repo under a root.

Ported from willow-2.0's `scripts/repo_fleet_sweep.py`, which ran weekly as
`repo-fleet-sweep.service` until that repo was decommissioned. The survey logic
below is the original's, kept close to verbatim because it earned its shape over
a year of real runs; what changed is the two places it could not survive the
move — repo discovery and the SOIL write.

**Read-only by design.** It reports, and optionally raises flags. It never
fetches, pulls, commits, deletes a branch, or drops a stash. Cleanup is offered
as a report line an operator can act on, never performed.

What it looks for, one finding per line per repo:

  * diverged  — ahead AND behind upstream
  * unpushed  — ahead only
  * no upstream tracking on a non-default branch
  * untracked *source* files (a deliverable living outside git)
  * tracked-but-dirty files — runtime state committed into a repo
  * branch litter above a threshold
  * merged linked worktrees that are clean and fully in the default branch
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

#: Suffixes that make an untracked file look like a deliverable rather than
#: scratch. A stray `.py` or `.md` outside git is worth a look; a `.pyc` is not.
SOURCE_SUFFIXES = {".py", ".sh", ".js", ".ts", ".rs", ".go", ".md", ".sql", ".toml", ".json"}

#: How deep under the root to look for repos. 1 finds `<root>/<repo>/.git`; 2 also
#: finds `<root>/<org>/<repo>/.git`.
#:
#: The original globbed `*/.git` and only that. It was written for a flat
#: `~/github/<repo>` tree, and the 2026-08-10 org-folder move put every repo one
#: level down — so on the new layout it reported "2 repos" where there were 32,
#: and called the other 30 neither clean nor flagged but simply absent. A sweep
#: that silently surveys 6% of the fleet is worse than one that fails, because
#: the report still looks like a report.
DEFAULT_MAX_DEPTH = 2

#: Flags land here. willow-mcp collection names are flat — `_validate_collection`
#: rejects the original's `willow/flags` — and this name is inside the willow
#: manifest's existing `willow_*` store_scope, so raising flags needs no manifest
#: change.
DEFAULT_FLAG_COLLECTION = "willow_flags"


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=30,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _git_ok(repo: Path, *args: str) -> bool:
    """Run a git command for its exit status only (no stdout captured)."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, timeout=30,
    ).returncode == 0


def _default_branch(repo: Path) -> Optional[str]:
    """The repo's integration branch — 'master' or 'main', whichever exists."""
    for b in ("master", "main"):
        if _git_ok(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{b}"):
            return b
    return None


def find_repos(root: Path, max_depth: int = DEFAULT_MAX_DEPTH) -> list[Path]:
    """Every git repo at or above `max_depth` under `root`, nearest first.

    Both layouts are searched rather than one being chosen, because this fleet
    holds both at once: `safe-app-store-public` sits directly under `~/github`
    while everything else lives under an org folder. Deduplicated and sorted so
    a repo reachable at two depths is surveyed once.
    """
    found: set[Path] = set()
    for depth in range(1, max(1, max_depth) + 1):
        pattern = "/".join(["*"] * depth) + "/.git"
        for p in root.glob(pattern):
            # A `.git` dir is a plain repo; a `.git` FILE is a worktree or
            # submodule pointer. Both are real repos worth surveying.
            if p.is_dir() or p.is_file():
                found.add(p.parent)
    return sorted(found)


def worktree_findings(repo: Path) -> list[str]:
    """Merged-but-present linked worktrees: clean AND fully contained in the
    default branch, so safe to reap.

    A worktree is flagged only when every one of these holds, so the operator can
    act on the report without re-verifying:
      - it is a linked worktree, not the primary checkout,
      - it tracks a real branch (detached HEADs are left for a human),
      - its working tree is clean (any uncommitted work → never flagged),
      - its HEAD is an ancestor of the default branch (fully merged).

    Local refs only — the sweep does not fetch, so "merged" means merged into the
    *local* default branch. That is the safe direction: a tip that has not been
    merged is never an ancestor, so this cannot produce a false "reapable".
    """
    porcelain = _git(repo, "worktree", "list", "--porcelain")
    if not porcelain:
        return []
    default = _default_branch(repo)
    if not default:
        return []

    blocks: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in porcelain.splitlines():
        if not line.strip():
            if cur:
                blocks.append(cur)
                cur = {}
            continue
        key, _, val = line.partition(" ")
        cur[key] = val
    if cur:
        blocks.append(cur)

    findings: list[str] = []
    for blk in blocks:
        wt = blk.get("worktree", "")
        if not wt or "bare" in blk or "detached" in blk:
            continue
        wt_path = Path(wt)
        if wt_path.resolve() == repo.resolve():
            continue  # the primary checkout is never a leftover
        head = blk.get("HEAD", "")
        branch = blk.get("branch", "").replace("refs/heads/", "")
        if not head or not branch or branch == default:
            continue
        if _git(wt_path, "status", "--porcelain"):
            continue  # uncommitted work — never flag
        if _git_ok(repo, "merge-base", "--is-ancestor", head, default):
            findings.append(
                f"merged worktree {wt_path.name!r} (branch {branch!r}) is clean and "
                f"fully in {default} — reap: git worktree remove {wt} "
                f"&& git branch -d {branch}"
            )
    return findings


def survey_repo(repo: Path, branch_limit: int = 15, root: Optional[Path] = None) -> dict:
    """One repo's hygiene record. Pure observation — nothing here writes."""
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    # An unborn repo — cloned empty, no commits yet — has no resolvable HEAD, so
    # `rev-parse --abbrev-ref` fails and _git returns "". Read the symbolic ref
    # instead, which is set from the moment the repo exists. Without this the
    # repo reports `on branch '' with no upstream tracking`, which is true only in
    # the way that a question with no subject is true: it reads as a finding when
    # the honest answer is "nothing has happened here yet".
    unborn = False
    if not branch:
        symref = _git(repo, "symbolic-ref", "-q", "--short", "HEAD")
        if symref:
            branch, unborn = symref, True
    status = _git(repo, "status", "--porcelain")
    lines = [ln for ln in status.splitlines() if ln.strip()]
    untracked = [ln[3:] for ln in lines if ln.startswith("??")]
    dirty_tracked = [ln for ln in lines if not ln.startswith("??")]

    ahead = behind = None
    upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream:
        counts = _git(repo, "rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        if counts:
            b, a = counts.split()
            ahead, behind = int(a), int(b)

    branches = _git(repo, "branch", "--format=%(refname:short)").splitlines()
    stashes = _git(repo, "stash", "list").splitlines()
    untracked_source = [f for f in untracked if Path(f).suffix in SOURCE_SUFFIXES]

    findings: list[str] = []
    if ahead and behind:
        findings.append(f"diverged: ahead {ahead} / behind {behind} of {upstream}")
    elif ahead:
        findings.append(f"unpushed: ahead {ahead} of {upstream}")
    if unborn:
        # Reported, not silenced: an empty checkout in the fleet is worth seeing
        # once. But it is not "untracked branch" — there is nothing to track yet.
        findings.append(f"no commits yet (unborn {branch!r})")
    elif branch not in ("master", "main") and not upstream:
        findings.append(f"on branch {branch!r} with no upstream tracking")
    if untracked_source:
        findings.append(f"{len(untracked_source)} untracked source files: "
                        + ", ".join(untracked_source[:5])
                        + (" …" if len(untracked_source) > 5 else ""))
    if len(dirty_tracked) >= 5:
        findings.append(f"{len(dirty_tracked)} tracked files dirty (runtime state in git?)")
    if len(branches) > branch_limit:
        findings.append(f"branch litter: {len(branches)} local branches")
    findings.extend(worktree_findings(repo))

    # `name` is relative to the root when one is given, so an org-layout sweep
    # reports `willow-memory/willow` rather than a bare `willow` that collides
    # with every other repo of that name.
    try:
        name = str(repo.relative_to(root)) if root else repo.name
    except ValueError:
        name = repo.name

    return {
        "repo": name,
        "path": str(repo),
        "branch": branch,
        "upstream": upstream or None,
        "ahead": ahead,
        "behind": behind,
        "untracked": len(untracked),
        "untracked_source": untracked_source,
        "dirty_tracked": len(dirty_tracked),
        "branches": len(branches),
        "stashes": stashes,
        "findings": findings,
    }


def sweep(root: Path, branch_limit: int = 15,
          max_depth: int = DEFAULT_MAX_DEPTH) -> list[dict]:
    """Survey every repo under `root`."""
    return [survey_repo(r, branch_limit, root=root)
            for r in find_repos(root, max_depth)]


def emit_flags(surveys: list[dict], collection: str = DEFAULT_FLAG_COLLECTION) -> int:
    """Raise one SOIL flag per repo with findings. Returns the count written.

    The original wrote through willow-2.0's `core.soil.put` into a path-shaped
    namespace (`willow/flags`). willow-mcp's collections are flat and regex
    validated, so the namespace becomes a collection name — see
    DEFAULT_FLAG_COLLECTION for why this particular one needs no manifest change.

    The flag id is stable per repo, so a re-run updates the existing flag rather
    than accumulating a new one every week.
    """
    from .db import Store

    store = Store()
    count = 0
    for s in surveys:
        if not s["findings"]:
            continue
        store.put(
            collection,
            {
                "kind": "repo_hygiene",
                "repo": s["repo"],
                "path": s["path"],
                "branch": s["branch"],
                "findings": s["findings"],
                "fix_path": ("operator review: push/reconcile, adopt or discard "
                             "untracked, prune branches"),
                "source": "willow-mcp repo-sweep",
                "status": "open",
            },
            record_id=f"repo-sweep-{s['repo'].replace('/', '-')}",
        )
        count += 1
    return count


def format_report(root: Path, surveys: list[dict], as_json: bool = False) -> str:
    flagged = [s for s in surveys if s["findings"]]
    if as_json:
        return json.dumps(
            {"root": str(root), "repos": len(surveys), "flagged": flagged}, indent=2)
    out = [f"[repo-sweep] {len(surveys)} repos under {root}, "
           f"{len(flagged)} with findings, {len(surveys) - len(flagged)} clean"]
    for s in flagged:
        out.append(f"\n  {s['repo']} ({s['branch']})")
        out.extend(f"    - {f}" for f in s["findings"])
    return "\n".join(out)
