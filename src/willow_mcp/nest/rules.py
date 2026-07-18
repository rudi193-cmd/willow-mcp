"""willow_mcp.nest.rules — Nest classification rules: public seed + local store.

The live drop-folder router (intake.py) classifies files by FILENAME into a
*track* (journal / legal / financial / photos / …). This module holds the rules
that map a filename to a track.

The package ships a generic, PII-free template (rules.seed.json). The live
ruleset is the operator's local store at $WILLOW_HOME/nest_rules.json (override:
$WILLOW_NEST_RULES), materialized from the seed on first use. Ratified rule
deltas mutate the local store and bump its version — never the seed, never code.
The classifier NEVER rewrites its own rules; intake.py proposes deltas (a flag),
the human ratifies.

Adapted from rudi193-cmd/willow-2.0 sap/core/nest_rules.py (the seed there had
leaked the operator's private keywords — case numbers, medical/legal matters;
this port ships a neutral template instead and keeps the operator's real rules
in their local store only).
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from .. import paths

SEED_PATH = Path(__file__).parent / "rules.seed.json"

_cache: dict = {"path": None, "mtime": None, "rules": None}


def rules_path() -> Path:
    override = os.environ.get("WILLOW_NEST_RULES")
    if override:
        return Path(override).expanduser()
    return paths.willow_home() / "nest_rules.json"


def load_rules() -> dict:
    """Local store if present (materializing from seed on first use), else seed.

    Cached by (path, mtime) so ratified deltas are picked up without a restart.
    """
    path = rules_path()
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SEED_PATH, path)
        except OSError:
            path = SEED_PATH  # read-only environment — serve the seed directly

    mtime = path.stat().st_mtime
    if _cache["path"] == path and _cache["mtime"] == mtime:
        return _cache["rules"]

    rules = json.loads(path.read_text())
    _cache.update(path=path, mtime=mtime, rules=rules)
    return rules


def _reset_cache() -> None:
    _cache.update(path=None, mtime=None, rules=None)


def version() -> str:
    return load_rules().get("version", "unversioned")


def should_ignore(filename: str) -> bool:
    """OS noise the Nest should never touch."""
    ignore = load_rules().get("ignore", {})
    n = filename.lower()
    if n in set(ignore.get("names", [])):
        return True
    return bool(ignore.get("dot_prefix", True)) and n.startswith(".")


def classify(filename: str) -> str | None:
    """Track for a filename, or None if unknown. Order in the rules file wins."""
    if should_ignore(filename):
        return None

    rules = load_rules()
    n = filename.lower()
    ext = Path(filename).suffix.lower()

    for track, spec in rules.get("tracks", {}).items():
        for pattern in spec.get("patterns", []):
            if re.match(pattern, filename):
                return track
        if any(k in n for k in spec.get("keywords", [])):
            return track

    images = rules.get("images", {})
    if ext in set(images.get("exts", [])):
        if any(k in n for k in images.get("personal_keywords", [])):
            return images.get("personal_track", "photos_personal")
        if any(k in n for k in images.get("screenshot_keywords", [])):
            return images.get("screenshot_track", "screenshots")
        for pattern in images.get("camera_patterns", []):
            if re.match(pattern, filename):
                return images.get("camera_track", "photos_camera")
        return images.get("default_track", "screenshots")

    return None
