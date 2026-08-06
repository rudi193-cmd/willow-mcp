"""SessionEnd hook — stack snapshot capture when closeout is skipped."""

from __future__ import annotations

import json
import os
import sys

from .stack_snapshot import write_stack_snapshot


def handle(payload: dict) -> dict:
    app_id = os.environ.get("WILLOW_APP_ID", "willow")
    session_id = str(
        payload.get("session_id")
        or payload.get("conversation_id")
        or ""
    )
    result = write_stack_snapshot(app_id, session_id)
    return {"stack_snapshot": result}


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    out = handle(payload)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
