"""Keep helper modules consistent with the files on disk across Streamlit redeploys.

Seen live after a redeploy: Streamlit re-executed the new app.py but kept the OLD i18n module in
sys.modules, so a new text key raised KeyError. app.py stamps every local module with its file's
mtime after import; on the next run, if any local module is unstamped or its file has changed,
ALL local modules are dropped and imported again together (dropping only one would leave the
others holding references to its old version).

An unstamped module is one this guard never saw: in production that means it was loaded by an
older app version (seen live: the first deploy with the guard stamped an old i18n with the NEW
file's mtime, which would have hidden it). Tests import and patch modules before the app runs,
so the test suite sets WINDCAST_TESTING=1 and unstamped modules are then left alone.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

STAMP = "_wc_mtime_ns"


def _local(here: Path, trees: tuple[Path, ...] = ()) -> dict:
    """Modules next to app.py, plus every module inside the given package trees (backend/app).

    The backend package is part of the same deploy: after the 18.11.2026 redeploy the app showed
    the new texts but the OLD station names, because backend/app/sites.py stayed in sys.modules.
    """
    out = {}
    for name, mod in list(sys.modules.items()):
        path = getattr(mod, "__file__", None)
        if name == "__main__" or not path:
            continue
        p = Path(path).resolve()
        if p.parent == here or any(p.is_relative_to(t) for t in trees):
            out[name] = (mod, Path(path))
    return out


def drop_stale(here: Path, trees: tuple[Path, ...] = ()) -> list[str]:
    """Drop all local modules if any stamped one changed on disk; returns the dropped names."""
    local = _local(here, trees)
    trust_unstamped = os.environ.get("WINDCAST_TESTING") == "1"
    stale = False
    for mod, path in local.values():
        stamp = getattr(mod, STAMP, None)
        if stamp is None:
            stale |= not trust_unstamped
            continue
        try:
            stale |= path.stat().st_mtime_ns != stamp
        except OSError:
            stale = True
    if not stale:
        return []
    for name in local:
        del sys.modules[name]
    return sorted(local)


def stamp(here: Path, trees: tuple[Path, ...] = ()) -> None:
    """Record the file mtime of every local module that has no stamp yet."""
    for mod, path in _local(here, trees).values():
        if getattr(mod, STAMP, None) is None:
            try:
                setattr(mod, STAMP, path.stat().st_mtime_ns)
            except OSError:
                pass
