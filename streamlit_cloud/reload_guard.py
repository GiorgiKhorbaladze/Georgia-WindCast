"""Keep helper modules consistent with the files on disk across Streamlit redeploys.

Seen live after a redeploy: Streamlit re-executed the new app.py but kept the OLD i18n module in
sys.modules, so a new text key raised KeyError. app.py stamps every local module with its file's
mtime after import; on the next run, if any stamped module's file has changed, ALL local modules
are dropped and imported again together (dropping only one would leave the others holding
references to its old version). Modules without a stamp (imported by tests, or by a version of
the app before this guard) are left alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

STAMP = "_wc_mtime_ns"


def _local(here: Path) -> dict:
    out = {}
    for name, mod in list(sys.modules.items()):
        path = getattr(mod, "__file__", None)
        if name != "__main__" and path and Path(path).resolve().parent == here:
            out[name] = (mod, Path(path))
    return out


def drop_stale(here: Path) -> list[str]:
    """Drop all local modules if any stamped one changed on disk; returns the dropped names."""
    local = _local(here)
    stale = False
    for mod, path in local.values():
        stamp = getattr(mod, STAMP, None)
        if stamp is None:
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


def stamp(here: Path) -> None:
    """Record the file mtime of every local module that has no stamp yet."""
    for mod, path in _local(here).values():
        if getattr(mod, STAMP, None) is None:
            try:
                setattr(mod, STAMP, path.stat().st_mtime_ns)
            except OSError:
                pass
