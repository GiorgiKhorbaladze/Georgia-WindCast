"""Private forecast archive and the public projection of it (owner decision 21.11.2026).

Numeric MW forecasts (live ledger, backtest ledger, ``latest.csv``, day-ahead energy rows,
tournament predictions) are kept ONLY in a private GitHub repository (the "archive"). The public
``forecast-data`` branch receives a projection that holds no forecast value:

* scores aggregated over many cases (``leaderboard.json``, daily MAE/RMSE without per-day bias,
  day-ahead summary per model, ``tournament.json``);
* commitments: SHA-256 and row count of every archived ledger file. The public git history of
  ``commitments/ledger.json`` time-stamps each archive state, so anyone later given the archive
  can verify that the forecasts existed unchanged at that time, without the public seeing values.

Nothing is published in clear after its validity period ends either; that would need a separate
owner decision. Weather inputs are not MW forecasts and stay on the public branch.

Commands (forecasting/run.py): ``seed`` (one-off copy of the old public ledger into an empty
archive, every file hash-verified), ``publish`` (archive -> public projection, then a leak scan
that refuses to leave any forbidden column or file on the public side) and ``verify`` (archive
files against the public commitments: detects corruption or a partial restore).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import shutil
from pathlib import Path

import pandas as pd

# Paths that may hold MW forecast values: archive only, removed from the public tree.
PRIVATE_DIRS = ("ledger", "backtest")
PRIVATE_FILES = ("state.json", "evaluation/latest.csv", "evaluation/day_ahead_live.csv",
                 "evaluation/day_ahead_backtest.csv")
PRIVATE_GLOBS = ("evaluation/tournament_*.csv.gz",)
# Columns or JSON keys that carry a forecast value (or let one be recomputed from public actuals).
FORBIDDEN_COLUMNS = frozenset({"prediction_mw", "q10_mw", "q90_mw", "mw", "pred", "forecast_mwh", "bias",
                               "error_mwh"})
# Aggregates over many days/cases that ARE published (bias here is a whole-window mean per horizon).
AGGREGATE_FILES = ("evaluation/leaderboard.json", "evaluation/tournament.json")
COMMITMENTS = Path("commitments") / "ledger.json"
PUBLIC_SCAN_SKIP = ("weather", ".git")


class LeakError(RuntimeError):
    """A forecast value would be left on the public branch."""


class IntegrityError(RuntimeError):
    """Archive content does not match what was copied or committed."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ledger_files(root: Path) -> list[Path]:
    out = []
    for d in ("ledger", "backtest/ledger"):
        if (root / d).exists():
            out.extend(sorted((root / d).rglob("*.csv.gz")))
    return out


def private_paths(root: Path) -> list[Path]:
    found = [root / d for d in PRIVATE_DIRS if (root / d).exists()]
    found += [root / f for f in PRIVATE_FILES if (root / f).exists()]
    for g in PRIVATE_GLOBS:
        found += sorted(root.glob(g))
    return found


def seed(archive: Path, public: Path) -> dict:
    """Copy the old public ledger into an EMPTY archive (one-off migration), verifying every file.

    The public copies are not deleted here: ``publish`` removes them only after the archive has
    been pushed, so an interrupted run never loses data."""
    if (archive / "state.json").exists() or ledger_files(archive):
        return {"result": "archive_not_empty", "files": 0}
    copied = []
    for src in private_paths(public):
        items = [p for p in src.rglob("*") if p.is_file()] if src.is_dir() else [src]
        for f in items:
            dst = archive / f.relative_to(public)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            if sha256(dst) != sha256(f):
                raise IntegrityError(f"copy of {f.relative_to(public)} differs from the source")
            copied.append(str(f.relative_to(public)))
    for name in ("history_backtest.csv", "history_live.csv", "leaderboard.json", "tournament.json"):
        f = public / "evaluation" / name
        if f.exists() and not (archive / "evaluation" / name).exists():
            (archive / "evaluation").mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, archive / "evaluation" / name)
    if (public / "constraints.csv").exists() and not (archive / "constraints.csv").exists():
        shutil.copy2(public / "constraints.csv", archive / "constraints.csv")
    return {"result": "seeded", "files": len(copied)}


def _sanitized_history(src: Path) -> str:
    df = pd.read_csv(src) if src.exists() and src.read_text().strip() else pd.DataFrame()
    return df.drop(columns=[c for c in df.columns if c in FORBIDDEN_COLUMNS]).to_csv(index=False)


def _day_ahead_summary(src: Path) -> dict:
    """Per model: MAE over complete days and the number of days. No per-day value, no bias."""
    if not src.exists() or not src.read_text().strip():
        return {"models": []}
    df = pd.read_csv(src)
    ok = df[df["complete"].astype(bool)] if len(df) else df
    rows = []
    for m, g in ok.groupby("model_id"):
        err = (g["forecast_mwh"] - g["actual_mwh"]).abs()
        rows.append({"model_id": m, "days": int(len(g)), "mae_mwh": round(float(err.mean()), 1)})
    return {"models": rows}


def commitments(archive: Path) -> dict:
    files = {str(p.relative_to(archive)): {"sha256": sha256(p), "bytes": p.stat().st_size, "rows": _rows(p)}
             for p in ledger_files(archive)}
    return {"algorithm": "sha256 of the stored .csv.gz bytes (files are append-only gzip members)", "files": files}


def _rows(path: Path) -> int:
    text = gzip.decompress(path.read_bytes()).decode("utf-8")
    return max(0, sum(1 for line in text.splitlines() if line.strip()) - 1)


def publish(archive: Path, public: Path) -> dict:
    """Write the public projection of the archive and remove every private path from the public tree."""
    removed = []
    for p in private_paths(public):
        removed.append(str(p.relative_to(public)))
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    ev_src, ev_dst = archive / "evaluation", public / "evaluation"
    ev_dst.mkdir(parents=True, exist_ok=True)
    for rel in AGGREGATE_FILES:
        if (archive / rel).exists():
            shutil.copy2(archive / rel, public / rel)
    for name in ("history_backtest.csv", "history_live.csv"):
        src = ev_src / name if (ev_src / name).exists() else ev_dst / name  # old public copy before the first evaluation
        if src.exists():
            (ev_dst / name).write_text(_sanitized_history(src))
    for kind in ("live", "backtest"):
        (ev_dst / f"day_ahead_summary_{kind}.json").write_text(
            json.dumps(_day_ahead_summary(ev_src / f"day_ahead_{kind}.csv"), indent=1) + "\n")
    (public / COMMITMENTS).parent.mkdir(parents=True, exist_ok=True)
    (public / COMMITMENTS).write_text(json.dumps(commitments(archive), indent=1, sort_keys=True) + "\n")
    scan(public)
    return {"result": "published", "removed_from_public": removed}


def _columns(path: Path) -> set[str]:
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    name = path.name.removesuffix(".gz")
    if name.endswith(".csv"):
        head = raw.decode("utf-8", "replace").split("\n", 1)[0]
        return {c.strip() for c in head.split(",")}
    if name.endswith(".json"):
        keys: set[str] = set()

        def walk(o):
            if isinstance(o, dict):
                keys.update(o)
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(json.load(io.BytesIO(raw)))
        return keys
    return set()


def scan(public: Path) -> None:
    """Refuse a public tree that still holds a private path or a forecast column outside the
    whole-window aggregates."""
    left = [str(p.relative_to(public)) for p in private_paths(public)]
    if left:
        raise LeakError(f"private paths on the public side: {left}")
    for p in public.rglob("*"):
        rel = p.relative_to(public)
        if not p.is_file() or rel.parts[0] in PUBLIC_SCAN_SKIP or str(rel) in AGGREGATE_FILES:
            continue
        bad = _columns(p) & FORBIDDEN_COLUMNS
        if bad:
            raise LeakError(f"{rel} holds forecast columns {sorted(bad)}")


def verify(archive: Path, public: Path) -> dict:
    """Archive ledger files against the public commitments (corruption / incomplete restore)."""
    path = public / COMMITMENTS
    if not path.exists():
        return {"result": "no_commitments"}
    committed = json.loads(path.read_text())["files"]
    have = {str(p.relative_to(archive)): p for p in ledger_files(archive)}
    missing = sorted(set(committed) - set(have))
    # Ledger files only ever grow by appended gzip members, so the committed bytes must be an exact
    # prefix of the current file (a run whose public push failed leaves the archive slightly ahead).
    changed = sorted(k for k in committed if k in have and hashlib.sha256(
        have[k].read_bytes()[:committed[k]["bytes"]]).hexdigest() != committed[k]["sha256"])
    if missing or changed:
        raise IntegrityError(f"archive differs from the public commitments: missing={missing} changed={changed}")
    return {"result": "verified", "files": len(committed)}
