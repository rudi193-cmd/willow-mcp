#!/usr/bin/env python3
"""Runnable end-to-end demo of the willow-gate signing harness against a REAL
willow-mcp stdio server, with enforcement ON.

This is the shape a production agent harness takes: the harness (this process)
holds the per-agent secret, checks in once, and signs every tool call — the model
it drives never sees the secret. Run it to prove your setup end to end:

    python examples/signing_client.py

What it does (all in a throwaway $WILLOW_HOME):
  1. OPERATOR STEP — register an agent, minting its secret. In production this is
     `willow-mcp register-agent worker --max-trust 3` at the operator's terminal,
     and the printed secret is installed into the harness out-of-band. Here we call
     agent_registry directly so the demo is self-contained.
  2. Launch `python -m willow_mcp` as a stdio MCP server with
     WILLOW_MCP_ENFORCE_BINDING=1 (a registered agent must now sign every call).
  3. Connect a real MCP client, wrap it in SigningClientSession, check in, and:
       - a SIGNED write + read succeed,
       - an UNSIGNED call is denied by the gate,
       - check-out reconciles clean.

No secret and no signature is ever a tool argument — the credential rides the MCP
request's out-of-band _meta.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# Import from the installed package (run from the repo root, or `pip install -e .`).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from willow_mcp import agent_registry, signing  # noqa: E402


def _result(r) -> dict:
    return signing._result_dict(r)


def _setup_home() -> tuple[str, bytes]:
    """Throwaway $WILLOW_HOME with a manifest + a registered agent. Returns
    (home, secret). The register call is the operator's `register-agent`."""
    home = tempfile.mkdtemp(prefix="willow-signing-demo-")
    apps = Path(home) / "mcp_apps" / "worker"
    apps.mkdir(parents=True, exist_ok=True)
    (apps / "manifest.json").write_text(json.dumps({"permissions": ["full_access"]}))

    os.environ["WILLOW_HOME"] = home                      # so register writes here
    os.environ.pop("WILLOW_MCP_APPS_ROOT", None)
    out = agent_registry.register_agent("worker", max_trust=3)   # ← operator step
    print(f"[operator] registered 'worker' at trust ceiling 3; secret minted")
    return home, bytes.fromhex(out["secret_hex"])


async def main() -> int:
    home, secret = _setup_home()

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "willow_mcp"],                        # default = stdio MCP server
        env={**os.environ,
             "WILLOW_HOME": home,
             "WILLOW_MCP_APPS_ROOT": str(Path(home) / "mcp_apps"),
             "WILLOW_STORE_ROOT": str(Path(home) / "store"),
             "WILLOW_MCP_ENFORCE_BINDING": "1"},          # ← enforcement ON
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            harness = signing.SigningClientSession(session, "worker", secret)

            bound = await harness.bind(trust_level=3, tools=["read", "write"])
            print(f"[harness] checked in — session {bound['session_id'][:8]}… tier={bound['tier']}")

            put = _result(await harness.call(
                "store_put", {"collection": "notes", "record": {"text": "hello"},
                              "record_id": "n1"}))
            print(f"[signed]  store_put -> {'ok' if 'error' not in put else put}")

            unsigned = _result(await session.call_tool(
                "store_get", {"app_id": "worker", "collection": "notes", "record_id": "n1"}))
            print(f"[unsigned] store_get -> DENIED: {unsigned.get('error', unsigned)[:60]}…")

            got = _result(await harness.call(
                "store_get", {"collection": "notes", "record_id": "n1"}))
            print(f"[signed]  store_get -> {'ok' if 'error' not in got else got}")

            rec = _result(await harness.reconcile(tools=["read", "write"]))
            print(f"[harness] check-out reconcile -> clean={rec.get('clean')}")

            ok = ("error" not in put and "binding required" in unsigned.get("error", "")
                  and "error" not in got and rec.get("clean") is True)
            print("\nRESULT:", "PASS — enforcement runs end to end" if ok else "FAIL")
            return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
