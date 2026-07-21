"""Proactive dew delivery — Step 5 wiring without a parallel daemon.

``dew_surface()`` is already exposed via MCP ``commitment_surface`` and the
session-start skill (step 4). This module adds the third delivery path: an
optional worker idle hook that publishes non-empty surfacings to a signal file
hooks can read. Off by default (``WILLOW_MCP_COMMITMENT_PROACTIVE=1`` to enable).

Design: willow/design/willow-commitment-membrane.md (Step 5) · ΔΣ=42
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("willow_mcp.commitments.proactive")

_DEFAULT_INTERVAL_S = 300.0


def proactive_enabled() -> bool:
    return os.environ.get("WILLOW_MCP_COMMITMENT_PROACTIVE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def signal_path() -> Path:
    home = Path(os.environ.get("WILLOW_HOME", Path.home() / ".willow"))
    return home / "signals" / "commitment_dew.json"


def surfacings_to_payload(surfacings) -> list[dict]:
    out = []
    for s in surfacings:
        row = {"kind": s.kind, "fact": s.fact}
        uids = getattr(s, "uids", None)
        if uids is not None:
            row["uids"] = list(uids)
        out.append(row)
    return out


def publish_dew_signal(surfacings, *, now: Optional[datetime] = None) -> bool:
    """Write surfacings to the signal file; return True when anything was published."""
    if not surfacings:
        return False
    path = signal_path()
    payload = {
        "published_at": (now or datetime.now(timezone.utc)).isoformat(),
        "surfacings": surfacings_to_payload(surfacings),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True))
        os.replace(tmp, path)
        return True
    except OSError as exc:
        logger.warning("commitment dew signal write failed (%s): %s", path, exc)
        return False


def chain_heartbeat(primary: Callable, secondary: Callable) -> Callable:
    """Compose two ``on_heartbeat`` callbacks; secondary never blocks primary."""

    def _beat(**kwargs) -> None:
        primary(**kwargs)
        try:
            secondary(**kwargs)
        except Exception as exc:
            logger.warning("secondary heartbeat hook failed: %s", exc)

    return _beat


class CommitmentProactiveHook:
    """``on_heartbeat`` secondary: sample dew on idle ticks, publish when non-silent."""

    def __init__(
        self,
        *,
        surface_fn: Callable[[], list],
        interval_s: float = _DEFAULT_INTERVAL_S,
    ):
        self._surface_fn = surface_fn
        self._interval_s = float(interval_s)
        self._last_check = 0.0

    def __call__(self, *, tick_ok: bool = True, **_) -> None:
        if not proactive_enabled() or not tick_ok:
            return
        now = time.time()
        if now - self._last_check < self._interval_s:
            return
        self._last_check = now
        try:
            surfacings = self._surface_fn()
        except Exception as exc:
            logger.warning("commitment dew surface failed: %s", exc)
            return
        publish_dew_signal(surfacings)
