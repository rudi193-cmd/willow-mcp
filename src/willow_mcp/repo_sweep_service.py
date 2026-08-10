"""Installer-managed systemd user units for the weekly repo hygiene sweep.

Same doctrine as `worker_service`: install and uninstall only manage unit files
and daemon-reload. **They never start, stop, enable, or disable a live service.**
Whether the sweep runs is the operator's decision, not the installer's.

Two units, because the split is real: a `oneshot` service that does the work and
exits, and a `.timer` that owns the schedule. The predecessor
(`repo-fleet-sweep`, willow-2.0) used exactly this shape on
`Mon *-*-* 04:00:00` with `Persistent=true`, and that cadence is kept.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import repo_sweep

UNIT_PREFIX = "willow-mcp-repo-sweep"
SERVICE_UNIT = f"{UNIT_PREFIX}.service"
TIMER_UNIT = f"{UNIT_PREFIX}.timer"

#: Weekly, off-hours. Matches the predecessor exactly.
DEFAULT_ONCALENDAR = "Mon *-*-* 04:00:00"


@dataclass(frozen=True)
class RepoSweepConfig:
    python: Path
    workdir: Path
    willow_home: Path
    store_root: Path
    app_id: str
    root: Path
    collection: str
    oncalendar: str


def default_config() -> RepoSweepConfig:
    home = Path(os.environ.get("WILLOW_HOME", Path.home() / ".willow")).expanduser()
    store = Path(os.environ.get("WILLOW_STORE_ROOT", home / "store")).expanduser()
    return RepoSweepConfig(
        python=Path(sys.executable),
        workdir=Path.cwd().resolve(),
        willow_home=home.resolve(),
        store_root=store.resolve(),
        app_id=os.environ.get("WILLOW_APP_ID", "willow"),
        # The tree to survey, not a willow path — an operator with repos
        # elsewhere overrides it at install time.
        root=Path(os.environ.get("WILLOW_REPO_SWEEP_ROOT", Path.home() / "github")).expanduser().resolve(),
        collection=repo_sweep.DEFAULT_FLAG_COLLECTION,
        oncalendar=DEFAULT_ONCALENDAR,
    )


def _template(name: str) -> Path:
    return Path(__file__).resolve().parent / "bundle" / "deploy" / name


def unit_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base.expanduser() / "systemd" / "user"


def _safe(value: object, field: str) -> str:
    text = str(value)
    if not text or any(char in text for char in ("\n", "\r", '"')):
        raise ValueError(f"{field} contains characters unsafe for a systemd unit")
    return text


def render_units(config: RepoSweepConfig) -> dict[str, str]:
    """The .service and .timer bodies. Rendered together so the timer's
    `Unit=` can never drift from the service it schedules."""
    values = {
        "PYTHON": config.python,
        "WORKDIR": config.workdir,
        "WILLOW_HOME": config.willow_home,
        "WILLOW_STORE_ROOT": config.store_root,
        "APP_ID": config.app_id,
        "ROOT": config.root,
        "COLLECTION": config.collection,
        "ONCALENDAR": config.oncalendar,
        "SERVICE_UNIT": SERVICE_UNIT,
    }
    out: dict[str, str] = {}
    for unit, tmpl in ((SERVICE_UNIT, f"{UNIT_PREFIX}.service.template"),
                       (TIMER_UNIT, f"{UNIT_PREFIX}.timer.template")):
        rendered = _template(tmpl).read_text(encoding="utf-8")
        for key, value in values.items():
            safe = str(value) if key == "PYTHON" else _safe(value, key)
            rendered = rendered.replace(f"@{key}@", safe)
        if "@" in rendered:
            raise ValueError(f"{unit} template contains unresolved placeholders")
        # The same guard worker_service carries. These units exist *because*
        # willow-2.0 went away; one that named it would be reintroducing the
        # dependency this port removes.
        if "willow-2.0" in rendered:
            raise ValueError(f"{unit} must not reference willow-2.0")
        out[unit] = rendered
    return out


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        check=False, capture_output=True, text=True, timeout=15,
    )


def install_services(config: RepoSweepConfig, *, destination: Optional[Path] = None,
                     reload: bool = True) -> dict:
    root = Path(destination) if destination is not None else unit_dir()
    root.mkdir(parents=True, exist_ok=True)
    written = []
    for unit, body in render_units(config).items():
        path = root / unit
        path.write_text(body, encoding="utf-8")
        written.append(str(path))
    if reload:
        result = _systemctl("daemon-reload")
        if result.returncode != 0:
            raise RuntimeError(
                (result.stderr or result.stdout or "systemctl daemon-reload failed").strip())
    # started/enabled are always empty and that is the contract, not an omission.
    return {"installed": written, "started": [], "enabled": []}


def service_status(*, destination: Optional[Path] = None,
                   runner: Callable[..., subprocess.CompletedProcess] = _systemctl) -> dict:
    root = Path(destination) if destination is not None else unit_dir()
    units = []
    for name in (SERVICE_UNIT, TIMER_UNIT):
        path = root / name
        active = False
        if path.is_file():
            result = runner("is-active", name)
            active = result.returncode == 0 and result.stdout.strip() == "active"
        units.append({"unit": name, "path": str(path),
                      "installed": path.is_file(), "active": active})
    return {"services": units}


def uninstall_services(*, destination: Optional[Path] = None, reload: bool = True,
                       runner: Callable[..., subprocess.CompletedProcess] = _systemctl) -> dict:
    root = Path(destination) if destination is not None else unit_dir()
    status = service_status(destination=root, runner=runner)
    active = [u["unit"] for u in status["services"] if u["active"]]
    if active:
        raise RuntimeError(
            "refusing to uninstall an active repo-sweep unit; stop it explicitly first: "
            + ", ".join(active))
    removed = []
    for u in status["services"]:
        path = Path(u["path"])
        if path.is_file():
            path.unlink()
            removed.append(str(path))
    if reload:
        result = runner("daemon-reload")
        if result.returncode != 0:
            raise RuntimeError(
                (result.stderr or result.stdout or "systemctl daemon-reload failed").strip())
    return {"removed": removed}
