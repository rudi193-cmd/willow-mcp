"""dispatch_gate.py — SAFE-gated voice DISPATCH (WO-1 Step 5).

Spoken text crosses the same policy wall as typed input: scan for injection /
approval-bypass patterns, fail closed, then hand off to an injected handler
(the fleet chat path — ``infer_chat`` or equivalent at product wiring time).
The membrane never widens authority; a spoken destructive command hits the same
``Refused`` stop as a typed one.

FRANK records the FACT of each dispatch attempt (allowed / refused / guard hit) —
never the utterance text. Transition receipts for armed / endpoint / disarm live
in ``frank_bridge.py``.

Design: willow/design/willow-voice-ingress-membrane.md (Step 5) · ΔΣ=42
"""
from __future__ import annotations

from typing import Callable, Optional, Protocol, runtime_checkable

from willow_mcp.voice.voice_controller import Refused

Handler = Callable[[str, Optional[str]], str]
FrankAppend = Callable[[str, dict], None]


@runtime_checkable
class CommandHandler(Protocol):
    """Product-repo chat / command seam — inject the real handler at wiring time."""

    def __call__(self, text: str, speaker: Optional[str]) -> str: ...


def _default_handler(_text: str, _speaker: Optional[str]) -> str:
    raise Refused("voice dispatch handler not configured")


class SafeDispatchGate:
    """Drop-in ``gate_fn`` for ``VoiceController``.

    Policy order (fail-closed):
      1. reject empty utterances
      2. ``external_guard`` scan — BLOCKED patterns refuse immediately
      3. SUSPICIOUS patterns refuse (voice has no human-in-the-loop re-read)
      4. delegate to the injected handler; ``Refused`` propagates unchanged
    """

    def __init__(
        self,
        *,
        handler: Handler | None = None,
        frank_append: FrankAppend | None = None,
        project: str = "willow",
        app_id: str = "voice",
    ):
        self._handler = handler or _default_handler
        self._frank_append = frank_append
        self._project = project
        self._app_id = app_id

    def _record(self, event_type: str, content: dict) -> None:
        if self._frank_append is None:
            return
        payload = {
            "app_id": self._app_id,
            "project": self._project,
            **content,
        }
        self._frank_append(event_type, payload)

    def __call__(self, text: str, speaker: Optional[str]) -> str:
        from willow_mcp import external_guard

        clean = (text or "").strip()
        if not clean:
            self._record(
                "voice_dispatch_refused",
                {"speaker": speaker, "reason": "empty_utterance"},
            )
            raise Refused("empty utterance")

        hits = external_guard.scan(clean)
        verdict = external_guard.verdict(hits)
        if verdict == "BLOCKED":
            self._record(
                "voice_dispatch_refused",
                {
                    "speaker": speaker,
                    "reason": "guard_blocked",
                    "guard_hits": len(hits),
                    "chars": len(clean),
                },
            )
            raise Refused("command blocked by SAFE guard")
        if verdict == "SUSPICIOUS":
            self._record(
                "voice_dispatch_refused",
                {
                    "speaker": speaker,
                    "reason": "guard_suspicious",
                    "guard_hits": len(hits),
                    "chars": len(clean),
                },
            )
            raise Refused("suspicious command pattern")

        try:
            response = self._handler(clean, speaker)
        except Refused as exc:
            self._record(
                "voice_dispatch_refused",
                {
                    "speaker": speaker,
                    "reason": str(exc)[:80],
                    "chars": len(clean),
                },
            )
            raise
        except Exception as exc:
            self._record(
                "voice_dispatch_refused",
                {
                    "speaker": speaker,
                    "reason": f"handler_error:{type(exc).__name__}",
                    "chars": len(clean),
                },
            )
            raise Refused(str(exc)[:80]) from exc

        self._record(
            "voice_dispatch_allowed",
            {
                "speaker": speaker,
                "chars": len(clean),
                "response_chars": len(response or ""),
            },
        )
        return response or ""


def safe_dispatch_gate(
    *,
    handler: Handler | None = None,
    frank_append: FrankAppend | None = None,
    project: str = "willow",
    app_id: str = "voice",
) -> SafeDispatchGate:
    """Factory for ``VoiceController(gate_fn=safe_dispatch_gate(...))`` wiring."""
    return SafeDispatchGate(
        handler=handler,
        frank_append=frank_append,
        project=project,
        app_id=app_id,
    )
