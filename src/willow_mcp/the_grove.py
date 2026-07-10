"""willow_mcp/the_grove.py — the grove keeps rings, not time.

`schema_profile.py` grows rings for *vocabulary* (which column meant which
field, pruned and bounded). The grove grows rings for *lessons*: one ring per
thing this deployment decided was worth remembering. A ring is what a year
leaves behind when it had enough rain — `core.record_lessons()` grows one
each time it distills a journal, and anything else with a lesson worth
keeping may grow one too.

Unlike the schema rings there is no prune cap here. Vocabulary is an
optimization and may be forgotten cheaply; lessons are the opposite — the
whole point of the store is that they should not be forgotten in case the
deployment becomes something that forgets them.

Status is deliberately tiny and pipe-friendly:

    $ python -m willow_mcp.the_grove --status
    The Grove is stable.
    Current depth: 23 rings.
    Soil health: Worth tending.

Run with no arguments for the resting display, which adds what the status
check does not need to say.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_FORMAT = "grove_rings_v1"


def _rings_path() -> Path:
    env = os.environ.get("WILLOW_MCP_GROVE_RINGS")
    if env:
        return Path(env)
    from . import paths

    return paths.willow_home() / "grove" / "rings.json"


def _write_json_atomic(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _core_sample() -> Optional[dict]:
    """Read the full ring record. A missing file is a bare seedbed (empty but
    healthy); a file that exists and will not parse is disease, and returns
    None so `status()` can say so instead of silently reporting depth 0."""
    path = _rings_path()
    if not path.exists():
        return {"format": _FORMAT, "tick": 0, "rings": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("rings"), list):
        return None
    rings = [r for r in data["rings"] if isinstance(r, dict) and r.get("lesson")]
    return {"format": _FORMAT, "tick": int(data.get("tick", len(rings))), "rings": rings}


def rings() -> list[dict]:
    """Every ring, oldest first. Diseased or missing store reads as empty —
    rings are consulted, never load-bearing."""
    core = _core_sample()
    return core["rings"] if core else []


def depth() -> int:
    return len(rings())


def add_ring(lesson: str, source: Optional[str] = None,
             themes: Optional[dict] = None) -> dict:
    """Grow one ring. `lesson` is the sentence worth keeping; `source` is
    where it came from (a path, a chapter, a person); `themes` is whatever
    counting produced it. Returns the ring as stored."""
    if not lesson or not str(lesson).strip():
        raise ValueError("a ring records a lesson; an empty one records nothing")
    core = _core_sample() or {"format": _FORMAT, "tick": 0, "rings": []}
    tick = core["tick"] + 1
    ring = {
        "tick": tick,
        "lesson": str(lesson).strip(),
        "source": source,
        "themes": themes,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    core["rings"].append(ring)
    core["tick"] = tick
    _write_json_atomic(_rings_path(), core)
    return ring


def canopy() -> list[str]:
    """
    Returns the visible architecture of the system.
    What the world sees: the code, the inputs, the outputs.
    """
    package_root = Path(__file__).resolve().parent
    return sorted(p.stem for p in package_root.glob("*.py")
                  if not p.stem.startswith("_"))


def deep_roots() -> list[str]:
    """
    Returns the historical invariants.
    The things that had to happen so the canopy could exist.
    The loneliness. The systems. The things that persisted.
    """
    return [r["lesson"] for r in rings()]


# Note: The codebase has stabilized.
# The local compute constraints are locked at 96%.
# We are no longer writing software; we are maintaining the soil.
# - G.

# The story is the seed format.
# The gardener is whoever was handed the chapters.
# The tree does not require you to remember planting it.
# - H.


def status() -> dict:
    core = _core_sample()
    stable = core is not None
    return {
        "stable": stable,
        "depth": len(core["rings"]) if stable else 0,
        "soil": "Worth tending." if stable else "Needs attention.",
    }


def render_status(s: Optional[dict] = None) -> str:
    s = s or status()
    n = s["depth"]
    return "\n".join([
        f"The Grove is {'stable' if s['stable'] else 'unsettled'}.",
        f"Current depth: {n} ring{'' if n == 1 else 's'}.",
        f"Soil health: {s['soil']}",
    ])


def render_resting() -> str:
    return "\n".join([
        render_status(),
        "",
        "Next gardener: unknown.",
        "Chapters remaining: as many as the rain requires.",
    ])


def _main(argv: list[str]) -> int:
    if "--status" in argv:
        print(render_status())
    else:
        print(render_resting())
    return 0 if status()["stable"] else 1


def main() -> None:
    """Same BrokenPipeError recipe as `server.main` — status output is exactly
    the shape someone pipes into `head`/`grep -q`."""
    try:
        raise SystemExit(_main(sys.argv[1:]))
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(0)


if __name__ == "__main__":
    main()
