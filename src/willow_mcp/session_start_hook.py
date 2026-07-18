"""Supported-client SessionStart bridge to native ``session_enter``."""
from __future__ import annotations

import json
import os
import sys
import uuid


def handle(payload: dict) -> dict:
    from .server import session_enter

    workspace = (
        payload.get("workspace")
        or payload.get("workspace_root")
        or payload.get("cwd")
        or os.environ.get("WILLOW_PROJECT_ROOT", "")
    )
    session_id = str(
        payload.get("session_id") or payload.get("conversation_id") or uuid.uuid4()
    )
    result = session_enter(
        app_id=os.environ.get("WILLOW_APP_ID", "willow"),
        session_id=session_id,
        project=os.environ.get("WILLOW_HANDOFF_PROJECT", ""),
        workspace=str(workspace or ""),
    )
    return {"additional_context": json.dumps(result, sort_keys=True)}


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(handle(payload if isinstance(payload, dict) else {})))
    except Exception as exc:
        # Fail VISIBLY (Loki C303AA2F §3.3): the hook is failClosed=false so a
        # failure must not silently drop orientation. Surface it in the session
        # context AND on stderr so it is loud in both the transcript and logs.
        message = f"WILLOW session_enter FAILED — orientation did not run: {exc}"
        print(f"[willow.session_start] {message}", file=sys.stderr)
        print(json.dumps({"additional_context": message}))


if __name__ == "__main__":
    main()
