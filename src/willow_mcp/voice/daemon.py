"""daemon.py — live voice ingress daemon (WO-1 assembly).

Wires capture → wake → VAD → transcribe → SAFE dispatch → Kokoro speak with
FRANK transition receipts. The controller stays pure; this module is the
imperative-shell driver loop.

Run: ``willow-mcp voice`` (see server._cmd_voice) or ``VoiceDaemon(...).run()``.

Design: willow/design/willow-voice-ingress-membrane.md · ΔΣ=42
"""
from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Optional

from willow_mcp.voice.barge import BargeDetector
from willow_mcp.voice.capture import MicCapture
from willow_mcp.voice.dispatch_gate import SafeDispatchGate
from willow_mcp.voice.frank_bridge import VoiceDriver, VoiceFrankBridge, governance_frank_append
from willow_mcp.voice.kokoro_speak import BargeCoordinator, KokoroSpeaker
from willow_mcp.voice.silero_vad import SileroVadFn
from willow_mcp.voice.transcribe import FasterWhisperTranscriber
from willow_mcp.voice.voice_controller import Frame, VoiceController, VoiceConfig
from willow_mcp.voice.wake_gate import OpenWakeWordGate

logger = logging.getLogger("willow_mcp.voice.daemon")

Handler = Callable[[str, Optional[str]], str]


@dataclass
class VoiceDaemonConfig:
    app_id: str = "willow"
    project: str = "willow"
    wake_models: Sequence[str] = field(default_factory=tuple)
    wake_threshold: float = 0.6
    whisper_model: str = "base"
    kokoro_url: str | None = None
    kokoro_voice: str | None = None
    enable_frank: bool = True
    enable_kokoro: bool = True
    command_handler: Handler | None = None
    sample_rate: int = 16000
    frame_samples: int = 1280
    mic_device: int | None = None
    voice_config: VoiceConfig | None = None


def _echo_handler(text: str, speaker: Optional[str]) -> str:
    """Dev/smoke handler — acknowledges without echoing utterance content."""
    _ = text
    who = speaker or "operator"
    return f"Acknowledged, {who}."


def load_handler(spec: str) -> Handler:
    """Import ``module:callable`` as the dispatch handler."""
    if ":" not in spec:
        raise ValueError("handler spec must be module:callable")
    module_name, attr = spec.rsplit(":", 1)
    module = importlib.import_module(module_name)
    target = getattr(module, attr)
    if not callable(target):
        raise TypeError(f"{spec!r} is not callable")
    return target


def resolve_wake_models(configured: Sequence[str]) -> tuple[str, ...]:
    if configured:
        return tuple(configured)
    env = os.environ.get("WILLOW_VOICE_WAKE_MODELS", "").strip()
    if env:
        return tuple(p for p in env.replace(",", ":").split(":") if p.strip())
    return ()


@dataclass
class VoiceStack:
    controller: VoiceController
    driver: VoiceDriver
    barge: BargeDetector
    speaker: KokoroSpeaker | None = None


class VoiceDaemon:
    """Assemble and run the full voice ingress loop."""

    def __init__(self, config: VoiceDaemonConfig):
        self.config = config

    def build(self) -> VoiceStack:
        cfg = self.config
        wake_models = resolve_wake_models(cfg.wake_models)
        if not wake_models:
            raise RuntimeError(
                "wake models required: pass --wake-model or set WILLOW_VOICE_WAKE_MODELS"
            )

        handler = cfg.command_handler or _echo_handler
        frank_append = governance_frank_append(cfg.project) if cfg.enable_frank else None
        gate = SafeDispatchGate(
            handler=handler,
            frank_append=frank_append,
            project=cfg.project,
            app_id=cfg.app_id,
        )
        wake_gate = OpenWakeWordGate(
            wake_models,
            threshold=cfg.wake_threshold,
            expected_frame_samples=cfg.frame_samples,
        )
        vad = SileroVadFn(sample_rate=cfg.sample_rate)
        transcribe = FasterWhisperTranscriber(model_size=cfg.whisper_model)

        speaker: KokoroSpeaker | None = None
        barge_coord = BargeCoordinator()
        if cfg.enable_kokoro:
            speaker = KokoroSpeaker(
                url=cfg.kokoro_url,
                voice=cfg.kokoro_voice,
                barge=barge_coord,
            )
            tts_fn = speaker
        else:
            tts_fn = lambda _chunk: None

        controller = VoiceController(
            config=cfg.voice_config or VoiceConfig(wake_threshold=cfg.wake_threshold),
            wake_gate=wake_gate,
            vad_fn=vad,
            transcribe_fn=transcribe,
            gate_fn=gate,
            tts_fn=tts_fn,
        )
        bridge = (
            VoiceFrankBridge(frank_append=frank_append, project=cfg.project, app_id=cfg.app_id)
            if frank_append is not None
            else None
        )
        driver = VoiceDriver(controller, frank_bridge=bridge)
        barge = BargeDetector(
            wake_gate=wake_gate,
            vad_fn=vad,
            wake_threshold=cfg.wake_threshold,
            barge=barge_coord,
        )
        return VoiceStack(controller=controller, driver=driver, barge=barge, speaker=speaker)

    def frame_source(self) -> Iterator[Frame]:
        return MicCapture(
            sample_rate=self.config.sample_rate,
            frame_samples=self.config.frame_samples,
            device=self.config.mic_device,
        ).frames()

    def run(self, *, frames: Iterator[Frame] | None = None) -> None:
        stack = self.build()
        stream = frames if frames is not None else self.frame_source()
        logger.info(
            "voice daemon listening (app_id=%s, frank=%s, kokoro=%s)",
            self.config.app_id,
            self.config.enable_frank,
            self.config.enable_kokoro,
        )
        try:
            for raw in stream:
                frame = stack.barge.enrich_for_controller(raw, stack.controller)
                stack.driver.step(frame)
        except KeyboardInterrupt:
            logger.info("voice daemon stopped")
