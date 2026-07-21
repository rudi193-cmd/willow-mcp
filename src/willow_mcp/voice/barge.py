"""barge.py — wake/VAD barge-in helpers during SPEAK (WO-1 Step 6).

The controller already honours ``frame.barge`` during SPEAK and returns to IDLE.
This module derives that flag from live PCM while the reply is playing, and ties
it to a ``BargeCoordinator`` so Kokoro playback can stop mid-chunk.

Design: willow/design/willow-voice-ingress-membrane.md (Step 6) · ΔΣ=42
"""
from __future__ import annotations

from typing import Callable, Optional

from willow_mcp.voice.kokoro_speak import BargeCoordinator
from willow_mcp.voice.voice_controller import Frame, State, VoiceController, WakeGate


class BargeDetector:
    """Mark incoming frames as barge when wake or VAD fires during SPEAK."""

    def __init__(
        self,
        *,
        wake_gate: WakeGate | None = None,
        wake_fn: Callable[[Frame], float] | None = None,
        vad_fn: Callable[[Frame], bool] | None = None,
        wake_threshold: float = 0.6,
        barge: BargeCoordinator | None = None,
    ):
        self._wake_gate = wake_gate
        self._wake_fn = wake_fn
        self._vad_fn = vad_fn
        self._wake_threshold = wake_threshold
        self._barge = barge or BargeCoordinator()

    @property
    def coordinator(self) -> BargeCoordinator:
        return self._barge

    def _wake_score(self, frame: Frame) -> float:
        if self._wake_gate is not None:
            return self._wake_gate.score(frame)
        if self._wake_fn is not None:
            return self._wake_fn(frame)
        return frame.wake_score

    def _is_speech(self, frame: Frame) -> bool:
        if self._vad_fn is not None:
            return self._vad_fn(frame)
        return frame.is_speech

    def enrich(self, frame: Frame, *, speaking: bool) -> Frame:
        if not speaking or frame.mute:
            return frame
        if frame.barge:
            self._barge.signal_barge()
            return frame
        score = self._wake_score(frame)
        if score >= self._wake_threshold or self._is_speech(frame):
            self._barge.signal_barge()
            return Frame(
                seq=frame.seq,
                wake_score=frame.wake_score,
                is_speech=frame.is_speech,
                mute=frame.mute,
                barge=True,
                pcm=frame.pcm,
            )
        return frame

    def enrich_for_controller(self, frame: Frame, controller: VoiceController) -> Frame:
        return self.enrich(frame, speaking=controller.state is State.SPEAK)
