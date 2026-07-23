#!/usr/bin/env python3
"""Minimal stdio MCP client — boot a server, initialize, list tools, call some.

Usage:
  mcpdrive.py --cmd "python3 sap/sap_mcp.py" --cwd /workspace/willow-2.0 list
  mcpdrive.py --cmd "..." --cwd ... call <tool> '<json-args>'
"""
import argparse, json, os, subprocess, sys, threading, time

class Server:
    def __init__(self, cmd, cwd, env=None):
        self.p = subprocess.Popen(
            cmd, shell=True, cwd=cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env={**os.environ, **(env or {})},
        )
        self._id = 0
        self.stderr_tail = []
        threading.Thread(target=self._drain_err, daemon=True).start()

    def _drain_err(self):
        for line in self.p.stderr:
            self.stderr_tail.append(line.rstrip())
            if len(self.stderr_tail) > 60:
                self.stderr_tail.pop(0)

    def _send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._id += 1
            msg["id"] = self._id
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        if notify:
            return None
        return self._read_reply(self._id)

    def _read_reply(self, want_id, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("server closed stdout.\nSTDERR:\n" + "\n".join(self.stderr_tail[-30:]))
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("id") == want_id:
                return obj
        raise TimeoutError("no reply.\nSTDERR:\n" + "\n".join(self.stderr_tail[-30:]))

    def initialize(self):
        r = self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcpdrive", "version": "0.1"},
        })
        self._send("notifications/initialized", {}, notify=True)
        return r

    def list_tools(self):
        return self._send("tools/list", {})

    def call(self, name, args):
        return self._send("tools/call", {"name": name, "arguments": args})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--env", default="")  # k=v,k=v
    ap.add_argument("action", choices=["list", "call", "boot", "script"])
    ap.add_argument("rest", nargs="*")
    a = ap.parse_args()
    env = {}
    for kv in a.env.split(",") if a.env else []:
        if "=" in kv:
            k, v = kv.split("=", 1); env[k] = v
    s = Server(a.cmd, a.cwd, env)
    try:
        init = s.initialize()
        si = init.get("result", {}).get("serverInfo", {})
        print(f"[boot ok] {si.get('name')} {si.get('version')}", file=sys.stderr)
        if a.action == "boot":
            return
        if a.action == "list":
            r = s.list_tools()
            tools = r.get("result", {}).get("tools", [])
            print(f"TOOLS={len(tools)}")
            for t in tools:
                print(t["name"])
        elif a.action == "call":
            name = a.rest[0]
            args = json.loads(a.rest[1]) if len(a.rest) > 1 else {}
            r = s.call(name, args)
            print(json.dumps(r.get("result", r), indent=2)[:4000])
        elif a.action == "script":
            # rest = path to a JSONL file of {"tool":..., "args":{...}}
            for line in open(a.rest[0]):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                spec = json.loads(line)
                print(f"\n===== CALL {spec['tool']} {json.dumps(spec.get('args', {}))} =====")
                try:
                    r = s.call(spec["tool"], spec.get("args", {}))
                    res = r.get("result", r)
                    # unwrap MCP content text if present
                    if isinstance(res, dict) and "content" in res:
                        for c in res["content"]:
                            if c.get("type") == "text":
                                print(c["text"][:1500])
                        if res.get("isError"):
                            print("[isError=true]")
                    else:
                        print(json.dumps(res, indent=2)[:1500])
                except Exception as e:
                    print(f"[DRIVER ERROR] {e}")
    finally:
        s.p.terminate()

if __name__ == "__main__":
    main()
