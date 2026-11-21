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
import json
import os
import re
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
RUNS_LOG = Path("commitments") / "runs.jsonl"  # one line per publish, with the GitHub Actions run
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


def _public_private_files(public: Path) -> list[Path]:
    out = []
    for src in private_paths(public):
        out.extend(sorted(p for p in src.rglob("*") if p.is_file()) if src.is_dir() else [src])
    return out


def _is_ledger(rel: Path) -> bool:
    return rel.suffixes[-2:] == [".csv", ".gz"] and "ledger" in rel.parts


def _prefix(short: bytes, long: bytes) -> bool:
    return long[:len(short)] == short


def seed(archive: Path, public: Path) -> dict:
    """Absorb every private file still on the public side into the archive, verifying each copy.

    Safe to run before every forecast AND tournament run, in any order and after any interruption:
    a file missing from the archive is copied and hash-checked; a ledger present in both must be a
    byte prefix of the archived one (append-only), otherwise the run stops instead of guessing.
    The public copies are not deleted here: ``publish`` removes them only after the archive has
    been pushed, and only when ``covered`` confirms every one of them is in the archive."""
    copied = []
    for f in _public_private_files(public):
        rel = f.relative_to(public)
        dst = archive / rel
        if dst.exists():
            if _is_ledger(rel) and not _prefix(f.read_bytes(), dst.read_bytes()):
                raise IntegrityError(f"public {rel} holds rows the archive does not; refusing to continue")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        if sha256(dst) != sha256(f):
            raise IntegrityError(f"copy of {rel} differs from the source")
        copied.append(str(rel))
    for name in ("history_backtest.csv", "history_live.csv", "leaderboard.json", "tournament.json"):
        f = public / "evaluation" / name
        if f.exists() and not (archive / "evaluation" / name).exists():
            (archive / "evaluation").mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, archive / "evaluation" / name)
    if (public / "constraints.csv").exists() and not (archive / "constraints.csv").exists():
        shutil.copy2(public / "constraints.csv", archive / "constraints.csv")
    return {"result": "seeded" if copied else "nothing_to_seed", "files": len(copied)}


def covered(archive: Path, public: Path) -> None:
    """Every private file on the public side must already be in the archive (ledgers as a byte
    prefix of the archived file) before anything is removed from the public side."""
    missing, diverged = [], []
    for f in _public_private_files(public):
        rel = f.relative_to(public)
        dst = archive / rel
        if not dst.exists():
            missing.append(str(rel))
        elif _is_ledger(rel) and not _prefix(f.read_bytes(), dst.read_bytes()):
            diverged.append(str(rel))
    if missing or diverged:
        raise IntegrityError(f"public files not in the archive: missing={missing} diverged={diverged}")


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


def _log_run(public: Path, digest: str) -> None:
    """Time evidence beyond the git commit date (which the committer sets): the GitHub Actions run
    that published this state. Its id, attempt and start time are recorded by GitHub itself
    (GET /repos/{repo}/actions/runs/{run_id}); the same digest is printed in the public run log.
    The archive commit SHA links the public line to the private state."""
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not run_id:  # local or test invocation: nothing to attest
        return
    entry = {"commitments_sha256": digest, "run_id": int(run_id),
             "run_attempt": int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")),
             "workflow": os.environ.get("GITHUB_WORKFLOW", ""), "repository": os.environ.get("GITHUB_REPOSITORY", ""),
             "archive_commit": os.environ.get("ARCHIVE_COMMIT", "")}
    path = public / RUNS_LOG
    with path.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    print(f"commitments_sha256={digest} run_id={run_id}")


def publish(archive: Path, public: Path) -> dict:
    """Write the public projection of the archive and remove every private path from the public tree."""
    covered(archive, public)  # AR1: never delete a public ledger the archive does not hold
    removed = []
    for p in private_paths(public):
        removed.append(str(p.relative_to(public)))
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    ev_src, ev_dst = archive / "evaluation", public / "evaluation"
    ev_dst.mkdir(parents=True, exist_ok=True)
    for rel in AGGREGATE_FILES:
        if (archive / rel).exists():  # AR2: bias removed at any level (a 1-day row's bias = that day's mean)
            (public / rel).write_text(json.dumps(_strip(json.loads((archive / rel).read_text())), indent=1) + "\n")
    for name in ("history_backtest.csv", "history_live.csv"):
        src = ev_src / name if (ev_src / name).exists() else ev_dst / name  # old public copy before the first evaluation
        if src.exists():
            (ev_dst / name).write_text(_sanitized_history(src))
    for kind in ("live", "backtest"):
        (ev_dst / f"day_ahead_summary_{kind}.json").write_text(
            json.dumps(_day_ahead_summary(ev_src / f"day_ahead_{kind}.csv"), indent=1) + "\n")
    (public / COMMITMENTS).parent.mkdir(parents=True, exist_ok=True)
    com = commitments(archive)
    text = json.dumps(com, indent=1, sort_keys=True) + "\n"
    (public / COMMITMENTS).write_text(text)
    _log_run(public, hashlib.sha256(text.encode()).hexdigest())
    scan(public)
    return {"result": "published", "removed_from_public": removed}


# AR2: the public tree is an allowlist, not a denylist. Outside weather/ only these files may exist.
PUBLIC_ALLOWED = ("README.md", "constraints.csv", str(COMMITMENTS), str(RUNS_LOG),
                  "evaluation/leaderboard.json", "evaluation/tournament.json",
                  "evaluation/history_backtest.csv", "evaluation/history_live.csv",
                  "evaluation/day_ahead_summary_live.json", "evaluation/day_ahead_summary_backtest.json")
HISTORY_COLUMNS = frozenset({"day", "cadence", "horizon_min", "model_id", "cases", "mae", "rmse"})
CONSTRAINT_COLUMNS = None  # owner-maintained input (curtailment notes), never a forecast; not parsed
# In public JSON every number must sit under one of these keys (scores, counts, provenance).
# Any other numeric leaf, or a string that is a bare number, is treated as a possible forecast value.
NUMERIC_KEYS = frozenset({
    "mae", "rmse", "skill", "skill_90ci", "mae_mwh", "cases", "days", "independent_days",
    "common_cases", "forecasts", "matured", "complete", "incomplete_or_missing", "late_share",
    "horizon_min", "horizon_h", "horizons_h", "model_version", "min_cases", "min_days", "weather_runs",
    "runs", "rows", "bytes", "run_id", "run_attempt", "run_number"})
# A dict with a "model_id" is a score row; it may carry only these keys (structural schema, AR2).
ROW_KEYS = frozenset({"model_id", "model_version", "cadence", "horizon_min", "horizon_h", "mae", "rmse",
                      "skill", "skill_90ci", "cases", "days", "independent_days", "common_cases", "evidence",
                      "mae_mwh", "late_share"})


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in FORBIDDEN_COLUMNS}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o
_NUMBER = re.compile(r"^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*$")


def _json_leaks(obj, rel: str) -> list[str]:
    bad: list[str] = []

    def walk(o, key, path):
        if isinstance(o, dict):
            if "model_id" in o and set(o) - ROW_KEYS:
                bad.append(f"{path} score row with keys outside the schema: {sorted(set(o) - ROW_KEYS)}")
            for k, v in o.items():
                if k in FORBIDDEN_COLUMNS:
                    bad.append(f"{path}.{k}")
                walk(v, k, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, key, f"{path}[{i}]")
        elif isinstance(o, bool) or o is None:
            return
        elif isinstance(o, (int, float)):
            if key not in NUMERIC_KEYS:
                bad.append(f"{path}={o!r}")
        elif isinstance(o, str) and _NUMBER.match(o) and key not in NUMERIC_KEYS:
            bad.append(f"{path}={o!r}")
    walk(obj, None, "$")
    return bad


def scan(public: Path) -> None:
    """Refuse a public tree that holds a private path, a file outside the allowlist, a CSV column
    outside its schema, or a JSON number that is not a score, count or provenance field."""
    left = [str(p.relative_to(public)) for p in private_paths(public)]
    if left:
        raise LeakError(f"private paths on the public side: {left}")
    for p in sorted(public.rglob("*")):
        rel = p.relative_to(public)
        if not p.is_file() or rel.parts[0] in PUBLIC_SCAN_SKIP:
            continue
        r = rel.as_posix()
        if r not in PUBLIC_ALLOWED:
            raise LeakError(f"{r} is not an allowed public file")
        if r.startswith("evaluation/history_"):
            head = set(p.read_text().split("\n", 1)[0].strip().split(",")) - {""}
            if head - HISTORY_COLUMNS:
                raise LeakError(f"{r} has columns outside the public schema: {sorted(head - HISTORY_COLUMNS)}")
        elif r.endswith(".json"):
            bad = _json_leaks(json.loads(p.read_text()), r)
            if bad:
                raise LeakError(f"{r} holds values that are not scores or counts: {bad[:5]}")
        elif r.endswith(".jsonl"):
            for n, line in enumerate(p.read_text().splitlines()):
                bad = _json_leaks(json.loads(line), r) if line.strip() else []
                if bad:
                    raise LeakError(f"{r} line {n + 1}: {bad[:5]}")


def private_status(status: int, body: dict | None, archive_repo: str, public_repo: str) -> str:
    """Positive proof only: GET /repos/{archive_repo}, made with a read-only token that HAS access
    to the archive (FORECAST_ARCHIVE_METADATA_TOKEN), must return 200 with private=true and
    visibility=private and the same full name. 404, 403, 5xx, a missing token or any other answer
    proves nothing (typo, deleted repository, token without access, outage) and stops the run."""
    if archive_repo.lower() == public_repo.lower():
        raise LeakError("the archive must be a separate repository, not this public one")
    if status != 200 or not body:
        raise LeakError(f"could not prove that {archive_repo} is private (HTTP {status}); refusing")
    if (body.get("private") is not True or body.get("visibility") != "private"
            or str(body.get("full_name", "")).lower() != archive_repo.lower()):
        raise LeakError(f"{archive_repo} is not a private repository (or the answer is for another one); refusing")
    return "private"


def check_private(archive_repo: str, public_repo: str, token: str | None) -> dict:
    import httpx

    if not token:
        raise LeakError("FORECAST_ARCHIVE_METADATA_TOKEN is not set; privacy cannot be proven; refusing")
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"}
    r = httpx.get(f"https://api.github.com/repos/{archive_repo}", headers=headers, timeout=20)
    body = r.json() if r.status_code == 200 else None
    return {"result": private_status(r.status_code, body, archive_repo, public_repo)}


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
