"""Manual live verification of the GSE source. Not part of CI; never writes to a database.

Usage: python -m app.ingestion.live_check [--periods N]
Exit codes: 0 = a current export was fetched and parsed; 1 = source problem; 2 = no recent file.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta

from app.config import get_settings
from app.ingestion.gse_job import build_client, due_labels
from app.ingestion.gse_parser import GseParseError, export_file_name, parse_wind_export
from app.ingestion.http_policy import FetchKind, fetch
from app.timeutil import utcnow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--periods", type=int, default=5)
    args = parser.parse_args(argv)
    settings = get_settings()
    now = utcnow()
    attempts = []
    with build_client(settings) as client:
        for label in due_labels(
            now, timedelta(seconds=settings.gse_publication_lag_seconds), args.periods
        ):
            url = settings.gse_base_url.rstrip("/") + "/" + export_file_name(label)
            result = fetch(client, url)
            entry: dict[str, object] = {
                "url": url,
                "outcome": result.kind.value,
                "http_status": result.status,
            }
            attempts.append(entry)
            if result.kind is FetchKind.NOT_PUBLISHED:
                continue
            if result.kind is not FetchKind.OK:
                entry["detail"] = result.detail
                print(json.dumps({"checked_at": now.isoformat(), "attempts": attempts}, indent=2))
                return 1
            try:
                reading = parse_wind_export(result.body)
            except GseParseError as exc:
                entry["error"] = f"{exc.code}: {exc}"
                print(json.dumps({"checked_at": now.isoformat(), "attempts": attempts}, indent=2))
                return 1
            entry.update(
                period_label_utc=reading.period_label_utc.isoformat(),
                period_label_local=reading.period_label_local,
                value_mw=reading.value_mw,
                quality=reading.quality,
                age_seconds=round((now - reading.period_label_utc).total_seconds()),
                last_modified=result.last_modified.isoformat() if result.last_modified else None,
            )
            print(json.dumps({"checked_at": now.isoformat(), "attempts": attempts}, indent=2))
            return 0
    print(json.dumps({"checked_at": now.isoformat(), "attempts": attempts}, indent=2))
    return 2


if __name__ == "__main__":
    sys.exit(main())
