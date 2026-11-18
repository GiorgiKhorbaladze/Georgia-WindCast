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


def test_unstamped_module_from_an_older_deploy_is_reloaded(tmp_path, monkeypatch):
    """Live case: the first deploy with the guard found an OLD i18n that had never been stamped."""
    make(tmp_path, "wc_old", "T = {}\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.import_module("wc_old")
    monkeypatch.setenv("WINDCAST_TESTING", "0")
    assert reload_guard.drop_stale(tmp_path.resolve()) == ["wc_old"]
    assert "wc_old" not in sys.modules


def test_unstamped_modules_are_kept_under_tests(tmp_path, monkeypatch):
    make(tmp_path, "wc_plain", "X = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    mod = importlib.import_module("wc_plain")
    assert reload_guard.drop_stale(tmp_path.resolve()) == []  # WINDCAST_TESTING=1 from conftest
    assert sys.modules["wc_plain"] is mod
    sys.modules.pop("wc_plain", None)


def test_backend_package_changes_also_reload_everything(tmp_path, monkeypatch):
    """Live 18.11.2026: new texts but OLD station names, because backend/app/sites.py was cached."""
    here, backend = tmp_path / "ui", tmp_path / "be"
    (backend / "wcpkg").mkdir(parents=True)
    here.mkdir()
    (backend / "wcpkg" / "__init__.py").write_text("", "utf-8")
    (backend / "wcpkg" / "sites.py").write_text("NAME = 'old'\n", "utf-8")
    make(here, "wc_data", "from wcpkg.sites import NAME\n")
    monkeypatch.syspath_prepend(str(backend))
    monkeypatch.syspath_prepend(str(here))
    importlib.import_module("wc_data")
    trees = ((backend / "wcpkg").resolve(),)
    reload_guard.stamp(here.resolve(), trees)
    assert reload_guard.drop_stale(here.resolve(), trees) == []

    sites = backend / "wcpkg" / "sites.py"
    sites.write_text("NAME = 'new'\n", "utf-8")
    st = sites.stat()
    os.utime(sites, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    assert reload_guard.drop_stale(here.resolve()) == []  # old behaviour: backend change unseen
    dropped = reload_guard.drop_stale(here.resolve(), trees)
    assert dropped == ["wc_data", "wcpkg", "wcpkg.sites"]
    assert importlib.import_module("wc_data").NAME == "new"
    for name in dropped:
        sys.modules.pop(name, None)
