"""Cursor/Claude PreToolUse hook entry — delegates to the bundle guard."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def main() -> None:
    hook_path = Path(__file__).resolve().parent / "bundle" / "hooks" / "pre_tool_use.py"
    spec = importlib.util.spec_from_file_location("willow_mcp_bundle_pre_tool_use", hook_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load pre_tool hook from {hook_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


if __name__ == "__main__":
    main()
