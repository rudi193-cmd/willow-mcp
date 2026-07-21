"""Installer-managed systemd user unit for the voice ingress daemon."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

UNIT_NAME = "willow-mcp-voice.service"


@dataclass(frozen=True)
class VoiceServiceConfig:
    python: Path
    workdir: Path
    willow_home: Path
    app_id: str
    wake_models: str
    kokoro_url: str
    kokoro_voice: str
    handler: str


def default_config() -> VoiceServiceConfig:
    home = Path(os.environ.get("WILLOW_HOME", Path.home() / ".willow")).expanduser()
    return VoiceServiceConfig(
        python=Path(sys.executable),
        workdir=Path.cwd().resolve(),
        willow_home=home.resolve(),
        app_id=os.environ.get("WILLOW_APP_ID", "willow"),
        wake_models=os.environ.get("WILLOW_VOICE_WAKE_MODELS", ""),
        kokoro_url=os.environ.get("WILLOW_KOKORO_URL", "http://localhost:5000/v1/audio/speech"),
        kokoro_voice=os.environ.get("WILLOW_KOKORO_VOICE", "am_michael"),
        handler=os.environ.get("WILLOW_VOICE_HANDLER", ""),
    )


def template_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / "bundle"
        / "deploy"
        / "willow-mcp-voice.service.template"
    )


def unit_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base.expanduser() / "systemd" / "user"


def _safe(value: object, field: str) -> str:
    text = str(value)
    if any(char in text for char in ("\n", "\r", '"')):
        raise ValueError(f"{field} contains characters unsafe for a systemd unit")
    return text


def render_unit(cfg: VoiceServiceConfig) -> str:
    raw = template_path().read_text(encoding="utf-8")
    replacements = {
        "@PYTHON@": _safe(cfg.python, "python"),
        "@WORKDIR@": _safe(cfg.workdir, "workdir"),
        "@WILLOW_HOME@": _safe(cfg.willow_home, "willow_home"),
        "@APP_ID@": _safe(cfg.app_id, "app_id"),
        "@WAKE_MODELS@": _safe(cfg.wake_models, "wake_models"),
        "@KOKORO_URL@": _safe(cfg.kokoro_url, "kokoro_url"),
        "@KOKORO_VOICE@": _safe(cfg.kokoro_voice, "kokoro_voice"),
        "@HANDLER@": _safe(cfg.handler, "handler"),
        "@VOICE_EXTRA@": _safe(
            f"--handler {cfg.handler}" if cfg.handler.strip() else "--echo",
            "voice_extra",
        ),
    }
    for key, val in replacements.items():
        raw = raw.replace(key, val)
    return raw


def install(cfg: VoiceServiceConfig | None = None) -> dict:
    cfg = cfg or default_config()
    if not cfg.wake_models.strip():
        return {"error": "WILLOW_VOICE_WAKE_MODELS or --wake-models is required"}
    dest = unit_dir() / UNIT_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_unit(cfg), encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    return {"status": "installed", "unit": str(dest)}


def status() -> dict:
    dest = unit_dir() / UNIT_NAME
    return {
        "unit_path": str(dest),
        "installed": dest.is_file(),
        "template": str(template_path()),
    }


def uninstall() -> dict:
    dest = unit_dir() / UNIT_NAME
    if dest.exists():
        dest.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    return {"status": "uninstalled", "unit": str(dest)}
