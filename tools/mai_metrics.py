#!/usr/bin/env python3
"""mai_metrics.py — record & report loop-convergence metrics, in SOIL.

Takes the "track how the loop is converging" bookkeeping off the model. Each
bite run records one metric into the willow `mai-loop-metrics` store collection
(through the gated store tools via wtool), and `report` prints the convergence
curve: as accumulated learnings grow, a fresh agent's new-gap count should fall
toward zero (loop-until-dry / ouroboros).

Usage:
  mai_metrics.py record '<json>'   # one bite metric (needs a "bite" id)
  mai_metrics.py report            # the convergence table + curve

Run with the willow-mcp venv python and the live willow env sourced.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

WTOOL = str(Path(__file__).resolve().parent / "wtool.py")
APP = os.environ.get("MAI_METRICS_APP", "safe-app-store")
COLL = os.environ.get("MAI_METRICS_COLLECTION", "mai-loop-metrics")

FIELDS = ["bite", "run_type", "target", "learnings_in", "files", "new_gaps",
          "tokens", "tool_uses", "duration_ms", "convergence", "committed"]


def _call_raw(name, args):
    return subprocess.run([sys.executable, WTOOL, name, json.dumps(args)],
                          capture_output=True, text=True).stdout


def _parse_objects(text):
    """store_list returns records as concatenated JSON objects, not an array."""
    dec, objs, i = json.JSONDecoder(), [], 0
    s = text.strip()
    while i < len(s):
        while i < len(s) and s[i] in " \n\r\t":
            i += 1
        if i >= len(s):
            break
        try:
            obj, end = dec.raw_decode(s, i)
            objs.append(obj)
            i = end
        except json.JSONDecodeError:
            break
    return objs


def record(rec: dict):
    rec = {"kind": "bite-metric", **rec}
    return _call_raw("store_put", {"app_id": APP, "collection": COLL,
                                   "record": rec, "record_id": rec.get("bite")})


def rows():
    items = _parse_objects(_call_raw("store_list", {"app_id": APP, "collection": COLL}))
    return sorted([x for x in items if x.get("kind") == "bite-metric" and x.get("bite") != "probe"],
                  key=lambda x: x.get("bite", ""))


def report():
    rs = rows()
    if not rs:
        print("(no metrics yet)")
        return
    hdr = (f"{'bite':<20}{'run':<10}{'learn':>6}{'files':>6}{'gaps':>6}"
           f"{'tokens':>9}{'tools':>6}{'sec':>7}  convergence")
    print(hdr)
    print("-" * len(hdr))
    for x in rs:
        sec = round(x.get("duration_ms", 0) / 1000)
        print(f"{x.get('bite',''):<20}{x.get('run_type',''):<10}"
              f"{x.get('learnings_in',''):>6}{x.get('files',''):>6}{x.get('new_gaps',''):>6}"
              f"{x.get('tokens',''):>9}{x.get('tool_uses',''):>6}{sec:>7}  {x.get('convergence','') or ''}")
    print("\nconvergence curve (new_gaps by learnings_in):")
    for x in rs:
        g = x.get("new_gaps", 0)
        print(f"  {x.get('learnings_in',0):>2} learnings in → {g} new gaps   "
              f"{'█'*g}{'·' if g==0 else ''}  [{x.get('bite')}]")


def main(argv):
    if len(argv) >= 2 and argv[0] == "record":
        print(record(json.loads(argv[1])))
    else:
        report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
