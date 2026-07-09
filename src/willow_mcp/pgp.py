"""PGP detached-signature verification (operator trust root).

Fail-closed when WILLOW_PGP_FINGERPRINT is set. Ported from willow-2.0/sap/core/gate.py
without dev_bypass. See docs/design/pgp-and-persona.md.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_FP_RE = re.compile(r"^[A-F0-9]{40}$", re.IGNORECASE)


def expected_fingerprint() -> str:
    return (os.environ.get("WILLOW_PGP_FINGERPRINT") or "").strip().upper()


def pgp_enabled() -> bool:
    fp = expected_fingerprint()
    return bool(fp and _FP_RE.match(fp))


def verify_detached(file_path: Path) -> tuple[bool, str]:
    """Verify file_path + file_path.name.sig against WILLOW_PGP_FINGERPRINT."""
    expected = expected_fingerprint()
    if not expected:
        return False, "WILLOW_PGP_FINGERPRINT unset"
    if not _FP_RE.match(expected):
        return False, "WILLOW_PGP_FINGERPRINT malformed"

    sig_path = file_path.parent / f"{file_path.name}.sig"
    if not sig_path.is_file():
        return False, f"no signature file: {sig_path.name}"

    try:
        result = subprocess.run(
            ["gpg", "--verify", "--status-fd=1", str(sig_path), str(file_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        return False, "gpg not found on PATH"
    except subprocess.TimeoutExpired:
        return False, "gpg verify timed out (5s)"
    except OSError as e:
        return False, f"gpg verify error: {e}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:200]
        return False, detail or "gpg verify failed"

    signer_fp = None
    for line in (result.stdout or "").splitlines():
        if line.startswith("[GNUPG:] VALIDSIG"):
            parts = line.split()
            if len(parts) >= 12:
                signer_fp = parts[11].upper()
                break

    if signer_fp is None:
        excerpt = (result.stdout or "")[:200].replace("\n", " ")
        return False, f"gpg ok but no VALIDSIG in status — {excerpt}"

    if signer_fp != expected:
        return (
            False,
            f"unexpected signer {signer_fp[:16]}... (expected {expected[:16]}...)",
        )
    return True, "signature verified"
