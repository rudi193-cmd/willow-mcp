"""frank_bridge.py — FRANK transition receipts for the voice membrane (WO-1 Step 5).

The controller's in-memory receipts already enforce receipt-not-recording.
This bridge mirrors those FACTS to FRANK — tick, event, speaker, counts —
never audio, transcript, or utterance text. Use ``VoiceDriver`` to wrap
``controller.step()`` so every new receipt is mirrored automatically.

Design: willow/design/willow-voice-ingress-membrane.md (Step 5) · ΔΣ=42
"""
from __future__ import annotations

from typing import Callable, Optional

from willow_mcp.voice.voice_controller import Frame, Receipt, VoiceController

FrankAppend = Callable[[str, dict], None]

# Mirror of the controller's forbidden receipt keys — refuse to leak at FRANK too.
_FORBIDDEN_FRANK_KEYS = frozenset(
    {"audio", "samples", "transcript", "text", "utterance", "waveform", "frames_raw"}
)

_EVENT_MAP = {
    "armed": "voice_armed",
    "false_positive": "voice_false_positive",
    "endpoint": "voice_endpoint",
    "identify": "voice_identify",
    "transcribe": "voice_transcribe",
    "dispatch": "voice_dispatch",
    "dispatch_refused": "voice_dispatch_refused",
    "speak": "voice_speak",
    "mute": "voice_mute",
    "barge_in": "voice_barge_in",
    "disarm": "voice_disarm",
    "unknown_speaker": "voice_unknown_speaker",
}


def frank_payload_from_receipt(receipt: Receipt, *, app_id: str = "voice") -> dict:
    """Receipt -> FRANK-safe content dict. Raises on forbidden keys."""
    leaked = _FORBIDDEN_FRANK_KEYS & receipt.meta.keys()
    if leaked:
        raise AssertionError(
            f"FRANK mirror would leak content via {sorted(leaked)} on {receipt.event!r}"
        )
    return {
        "app_id": app_id,
        "tick": receipt.tick,
        "event": receipt.event,
        **receipt.meta,
    }


class VoiceFrankBridge:
    """Mirrors controller transition receipts to FRANK."""

    def __init__(
        self,
        *,
        frank_append: FrankAppend,
        project: str = "willow",
        app_id: str = "voice",
    ):
        self._frank_append = frank_append
        self._project = project
        self._app_id = app_id

    def record(self, receipt: Receipt) -> None:
        event_type = _EVENT_MAP.get(receipt.event, f"voice_{receipt.event}")
        content = frank_payload_from_receipt(receipt, app_id=self._app_id)
        self._frank_append(event_type, content)


class VoiceDriver:
    """Wraps ``VoiceController.step`` and mirrors new receipts to FRANK."""

    def __init__(
        self,
        controller: VoiceController,
        *,
        frank_bridge: VoiceFrankBridge | None = None,
    ):
        self.controller = controller
        self._frank_bridge = frank_bridge

    def step(self, frame: Frame) -> None:
        before = len(self.controller.receipts)
        self.controller.step(frame)
        if self._frank_bridge is None:
            return
        for receipt in self.controller.receipts[before:]:
            self._frank_bridge.record(receipt)


def governance_frank_append(project: str = "willow") -> FrankAppend:
    """Build a ``frank_append`` callable backed by Postgres ``frank_ledger``.

    Raises ``RuntimeError`` when Postgres is unavailable — fail loud, not silent.
  """
    from willow_mcp.db import get_pg
    from willow_mcp.governance_ledger import GovernanceLedger

    def _append(event_type: str, content: dict) -> None:
        pg = get_pg()
        if pg is None:
            raise RuntimeError("postgres_unavailable for voice FRANK bridge")
        GovernanceLedger(pg).append(project, event_type, content)

    return _append
