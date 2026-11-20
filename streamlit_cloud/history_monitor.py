"""CLI for the 20-day GSE balance monitor and owner approvals (Issue #52).

``python history_monitor.py check --data-dir DATA [--force]``
    Runs one check against ``DATA/history`` (a checkout of the ``data`` branch). Exits 0 without
    contacting GSE when the previous attempt is younger than 20 days.

``python history_monitor.py approve --data-dir DATA --through REVISION --reason TEXT``
    Owner approval: every pending official-document value with a revision id up to REVISION
    becomes ``gse_document_approved``. Logged in the revision ledger.

Exit codes: 0 ok or skipped, 1 a document failed validation or structure checks, 2 GSE could not
be reached (data unchanged).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from gse_balance import DOWNLOAD_FAILED, INVALID, UNSUPPORTED, Fetched, check, load_archive, save_archive

HERE = Path(__file__).resolve().parent
SEED = HERE / "history_seed"


def http_fetch(client: httpx.Client):
    def fetch(url: str, headers: dict[str, str]) -> Fetched:
        resp = client.get(url, headers=headers)
        return Fetched(resp.status_code, resp.content if resp.status_code == 200 else b"",
                       resp.headers.get("etag", ""), resp.headers.get("last-modified", ""))
    return fetch


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GSE balance monitor (Issue #52)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--data-dir", type=Path, required=True)
    c.add_argument("--force", action="store_true", help="ignore the 20-day gate (manual run)")
    a = sub.add_parser("approve")
    a.add_argument("--data-dir", type=Path, required=True)
    a.add_argument("--through", type=int, required=True)
    a.add_argument("--reason", required=True)
    args = ap.parse_args(argv)
    directory = args.data_dir / "history"
    now = datetime.now(UTC)
    if args.cmd == "approve":
        archive, _seeded = load_archive(directory, SEED)
        done = archive.approve(now, args.through, args.reason)
        save_archive(directory, archive)
        print(json.dumps({"approved": len(done)}))
        return 0
    headers = {"User-Agent": ua} if (ua := os.environ.get("WINDCAST_GSE_USER_AGENT")) else {}
    with httpx.Client(timeout=httpx.Timeout(30.0), headers=headers, follow_redirects=False) as client, \
            tempfile.TemporaryDirectory() as work:
        report = check(directory, SEED, http_fetch(client), now, Path(work), force=args.force)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if str(report.get("result", "")).startswith("discovery_failed"):
        return 2
    states = set(report["documents"].values())
    return 1 if states & {INVALID, UNSUPPORTED, DOWNLOAD_FAILED} else 0


if __name__ == "__main__":
    sys.exit(main())
