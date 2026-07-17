"""Installer-managed systemd user units for standalone fast/batch workers.

Install and uninstall only manage unit files and daemon-reload. They never
start, stop, enable, or disable a live service.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

LANES = ("fast", "batch")
UNIT_PREFIX = "willow-mcp-worker"


@dataclass(frozen=True)
class WorkerServiceConfig:
    python: Path
    workdir: Path
    willow_home: Path
    store_root: Path
    pg_db: str
    app_id: str
    heartbeat_root: Path


def default_config() -> WorkerServiceConfig:
    home = Path(os.environ.get("WILLOW_HOME", Path.home() / ".willow")).expanduser()
    store = Path(os.environ.get("WILLOW_STORE_ROOT", home)).expanduser()
    return WorkerServiceConfig(
        python=Path(sys.executable).resolve(),
        workdir=Path.cwd().resolve(),
        willow_home=home.resolve(),
        store_root=store.resolve(),
        pg_db=os.environ.get("WILLOW_PG_DB", "willow"),
        app_id=os.environ.get("WILLOW_APP_ID", "willow-mcp"),
        heartbeat_root=Path(
            os.environ.get("WILLOW_WORKER_HEARTBEAT_ROOT", home / "worker_heartbeat")
        ).expanduser().resolve(),
    )


def template_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / "bundle"
        / "deploy"
        / "willow-mcp-worker.service.template"
    )


def unit_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base.expanduser() / "systemd" / "user"


def unit_name(lane: str) -> str:
    if lane not in LANES:
        raise ValueError(f"lane must be fast|batch, got {lane!r}")
    return f"{UNIT_PREFIX}-{lane}.service"


def _safe(value: object, field: str) -> str:
    text = str(value)
    if not text or any(char in text for char in ('\n', '\r', '"')):
        raise ValueError(f"{field} contains characters unsafe for a systemd unit")
    return text


def render_unit(
    lane: str,
    config: WorkerServiceConfig,
    *,
    template: str | None = None,
) -> str:
    unit_name(lane)
    source = template if template is not None else template_path().read_text(encoding="utf-8")
    values = {
        "LANE": lane,
        "PYTHON": config.python,
        "WORKDIR": config.workdir,
        "WILLOW_HOME": config.willow_home,
        "WILLOW_STORE_ROOT": config.store_root,
        "WILLOW_PG_DB": config.pg_db,
        "APP_ID": config.app_id,
        "HEARTBEAT_ROOT": config.heartbeat_root,
    }
    rendered = source
    for key, value in values.items():
        rendered = rendered.replace(f"@{key}@", _safe(value, key))
    if "@" in rendered:
        raise ValueError("worker service template contains unresolved placeholders")
    if "willow-2.0" in rendered:
        raise ValueError("worker service must not reference willow-2.0")
    return rendered


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


def install_services(
    config: WorkerServiceConfig,
    *,
    destination: Path | None = None,
    reload: bool = True,
) -> dict:
    root = Path(destination) if destination is not None else unit_dir()
    root.mkdir(parents=True, exist_ok=True)
    written = []
    for lane in LANES:
        path = root / unit_name(lane)
        path.write_text(render_unit(lane, config), encoding="utf-8")
        written.append(str(path))
    if reload:
        result = _systemctl("daemon-reload")
        if result.returncode != 0:
            raise RuntimeError(
                (result.stderr or result.stdout or "systemctl daemon-reload failed").strip()
            )
    return {"installed": written, "started": [], "enabled": []}


def service_status(
    *,
    destination: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = _systemctl,
) -> dict:
    root = Path(destination) if destination is not None else unit_dir()
    services = []
    for lane in LANES:
        name = unit_name(lane)
        path = root / name
        active = False
        if path.is_file():
            result = runner("is-active", name)
            active = result.returncode == 0 and result.stdout.strip() == "active"
        services.append(
            {"lane": lane, "unit": name, "path": str(path), "installed": path.is_file(), "active": active}
        )
    return {"services": services}


def uninstall_services(
    *,
    destination: Path | None = None,
    reload: bool = True,
    runner: Callable[..., subprocess.CompletedProcess] = _systemctl,
) -> dict:
    root = Path(destination) if destination is not None else unit_dir()
    status = service_status(destination=root, runner=runner)
    active = [service["unit"] for service in status["services"] if service["active"]]
    if active:
        raise RuntimeError(
            "refusing to uninstall active worker services; stop them explicitly first: "
            + ", ".join(active)
        )
    removed = []
    for service in status["services"]:
        path = Path(service["path"])
        if path.is_file():
            path.unlink()
            removed.append(str(path))
    if reload:
        result = runner("daemon-reload")
        if result.returncode != 0:
            raise RuntimeError(
                (result.stderr or result.stdout or "systemctl daemon-reload failed").strip()
            )
    return {"removed": removed, "stopped": []}
