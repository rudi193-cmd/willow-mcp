#!/usr/bin/env python3
"""wtool.py — call any willow-mcp tool from the shell over stdio.

The substrate under the other scripts here: it speaks the MCP stdio protocol to
a `python -m willow_mcp` subprocess, calls one tool, prints the text result.
Anything a model does by hand through the MCP client, a script can do through
this — that is the whole point (take the job off the model).

Usage:
  wtool.py <tool_name> '<json-args>'      # call a tool
  wtool.py --list [substr]                # list tool names (optionally filtered)

Environment: honors the live willow backend env (WILLOW_HOME, WILLOW_STORE_ROOT,
WILLOW_PG_*, WILLOW_APP_ID). Uses this interpreter (sys.executable), so run it
with the willow-mcp venv python to get the deps on path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


def _server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "willow_mcp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, env=dict(os.environ), bufsize=1,
    )

    def send(o):
        proc.stdin.write(json.dumps(o) + "\n")
        proc.stdin.flush()

    def read():
        while True:
            line = proc.stdout.readline()
            if not line:
                return None
            if line.strip():
                return json.loads(line)

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "wtool", "version": "1"}}})
    if read() is None:
        sys.stderr.write("[wtool] server did not start — is willow_mcp importable "
                         "under this python, and the env sourced?\n")
        sys.exit(2)
    send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    return proc, send, read


def call(name, args):
    proc, send, read = _server()
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
          "params": {"name": name, "arguments": args}})
    r = read()
    proc.terminate()
    res = r.get("result", r.get("error", {})) if r else {}
    if isinstance(res, dict):
        txt = "".join(c.get("text", "") for c in res.get("content", [])
                      if c.get("type") == "text")
        return txt or json.dumps(res)
    return json.dumps(res)


def list_tools(substr=""):
    proc, send, read = _server()
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    r = read()
    proc.terminate()
    names = [t["name"] for t in r["result"]["tools"]]
    return "\n".join(n for n in names if substr in n)


def main(argv):
    if not argv:
        sys.stderr.write(__doc__)
        return 2
    if argv[0] == "--list":
        print(list_tools(argv[1] if len(argv) > 1 else ""))
        return 0
    name = argv[0]
    args = json.loads(argv[1]) if len(argv) > 1 else {}
    print(call(name, args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
