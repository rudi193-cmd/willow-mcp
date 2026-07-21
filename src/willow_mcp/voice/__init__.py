"""Willow Voice Ingress Membrane — the fleet's boundary against the world's audio.

The exact mirror of Willow's egress membrane (Jarvis layer 1). The microphone is an ingress
membrane: pre-wake audio is never transcribed, never logged, and never leaves an in-memory ring
buffer. The wake-word gate IS the consent boundary — "always listening" and "privacy-preserving"
stop being in tension because the same structure enforces both.

The load-bearing idea: the state machine IS the security model. The core (voice_controller.py)
is a pure-script asyncio-drivable state machine with exactly one gated transition into the model
stages; every DSP/model stage is an injected callable, so the invariants are unit-testable with
synthetic frames. Real engine adapters (openWakeWord, etc.) live in wake_gate.py behind guarded
imports.

Design: willow/design/willow-voice-ingress-membrane.md (Appendix A is the verified skeleton).
"""
from willow_mcp.voice.voice_controller import (
    Frame,
    Receipt,
    Refused,
    State,
    StubWakeGate,
    VoiceConfig,
    VoiceController,
    WakeGate,
)

__all__ = [
    "Frame",
    "Receipt",
    "Refused",
    "State",
    "StubWakeGate",
    "VoiceConfig",
    "VoiceController",
    "WakeGate",
]

# Stage adapters (lazy heavy deps — import submodules directly when wiring live audio):
#   willow_mcp.voice.silero_vad.SileroVadFn
#   willow_mcp.voice.transcribe.FasterWhisperTranscriber
#   willow_mcp.voice.capture.MicCapture
