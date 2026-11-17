"""A redeploy must not leave old helper modules next to new code (live KeyError, 17.11.2026)."""

from __future__ import annotations

import importlib
import os
import sys

import reload_guard


def make(tmp_path, name, body):
    (tmp_path / f"{name}.py").write_text(body, "utf-8")


def test_changed_module_drops_all_local_modules(tmp_path, monkeypatch):
    make(tmp_path, "wc_texts", "T = {'old': 1}\n")
    make(tmp_path, "wc_user", "import wc_texts\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.import_module("wc_user")
    here = tmp_path.resolve()
    reload_guard.stamp(here)
    assert reload_guard.drop_stale(here) == []  # nothing changed: keep modules

    make(tmp_path, "wc_texts", "T = {'old': 1, 'ms': 2}\n")  # redeploy changes one file
    st = (tmp_path / "wc_texts.py").stat()
    os.utime(tmp_path / "wc_texts.py", ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    dropped = reload_guard.drop_stale(here)
    assert dropped == ["wc_texts", "wc_user"]  # both, so no module keeps the old version
    assert "ms" in importlib.import_module("wc_texts").T
    for name in dropped:
        sys.modules.pop(name, None)


def test_unstamped_modules_are_left_alone(tmp_path, monkeypatch):
    make(tmp_path, "wc_plain", "X = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    mod = importlib.import_module("wc_plain")
    os.utime(tmp_path / "wc_plain.py", ns=(0, 10**9))
    assert reload_guard.drop_stale(tmp_path.resolve()) == []
    assert sys.modules["wc_plain"] is mod
    sys.modules.pop("wc_plain", None)
