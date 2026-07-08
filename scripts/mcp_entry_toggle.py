#!/usr/bin/env python3
"""Add or remove a single http server entry in an .mcp.json file, idempotently.

Used by `scripts/willow-serve` to keep the serve-mode client entry in sync with
the running service. Extracted as a module so the toggle is unit-testable
without systemd.

    mcp_entry_toggle.py <mcp_json> <name> <url> {add|remove}
"""
import json
import sys


def toggle(path: str, name: str, url: str, action: str) -> None:
    with open(path) as f:
        cfg = json.load(f)
    servers = cfg.setdefault("mcpServers", {})
    if action == "add":
        servers[name] = {"type": "http", "url": url}
    elif action == "remove":
        servers.pop(name, None)
    else:
        raise ValueError(f"unknown action: {action!r} (expected add|remove)")
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def main(argv) -> int:
    if len(argv) != 4:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    path, name, url, action = argv
    toggle(path, name, url, action)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
