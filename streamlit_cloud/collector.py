"""Scheduled GSE collector for the Streamlit edition (run by .github/workflows/collect-gse.yml).

Each run backfills every 3-minute period of the last ``--lookback-hours`` that is not yet stored,
newest first. GSE keeps published files for at least 48 h (checked 2026-11-16, docs/sources/gse.md),
so irregular or delayed scheduled runs do not create gaps as long as one run succeeds within the
lookback window. Periods GSE never published stay gaps: after ``--missing-attempts`` runs with 404
they are no longer requested.

Exit codes: 0 ok (including "nothing new" and transient source errors); 1 data-integrity refusal
(schema drift, label mismatch, future label) so the workflow fails visibly; 2 source unreachable
and no reading newer than ``--alert-after-hours``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

# Backend first: this directory's app.py (the Streamlit entrypoint) must not shadow backend/app.
_HERE = str(Path(__file__).resolve().parent)
sys.path[:] = [p for p in sys.path if p not in ("", _HERE)]
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "backend"), _HERE]
from app.ingestion.gse_parser import (  # noqa: E402
    PARSER_VERSION,
    GseParseError,
    export_file_name,
    parse_wind_export,
)
from app.ingestion.http_policy import FetchKind, FetchResult, fetch  # noqa: E402
from store import Record, day_path, merge, parse_day_csv, render_day_csv  # noqa: E402

GSE_BASE = "https://admin.gse.com.ge/storage/uploads/fact/"
PERIOD = timedelta(minutes=3)
PUBLICATION_LAG = timedelta(seconds=75)
FUTURE_TOLERANCE = timedelta(seconds=60)
STATUS_PATH = "status/gse_collector.json"


def due_labels(now: datetime, hours: float) -> list[datetime]:
    newest = (now - PUBLICATION_LAG).replace(second=0, microsecond=0)
    newest -= timedelta(minutes=newest.minute % 3)
    return [newest - i * PERIOD for i in range(int(hours * 20))]


@dataclass
class RunReport:
    requested: int = 0
    inserted: int = 0
    revised: int = 0
    not_published: int = 0
    failures: int = 0
    integrity_error: str | None = None
    failure_kinds: dict[str, int] = field(default_factory=dict)


class Collector:
    def __init__(
        self,
        data_dir: Path,
        client_factory: Callable[[], httpx.Client],
        *,
        base_url: str = GSE_BASE,
        lookback_hours: float = 12,
        max_requests: int = 300,
        missing_attempts: int = 4,
        concurrency: int = 4,
    ) -> None:
        self.data_dir = data_dir
        self.client_factory = client_factory
        self.base_url = base_url.rstrip("/") + "/"
        self.lookback_hours = lookback_hours
        self.max_requests = max_requests
        self.missing_attempts = missing_attempts
        self.concurrency = concurrency
        self._days: dict[date, list[Record]] = {}
        self._dirty: set[date] = set()

    # -- storage
    def _load(self, day: date) -> list[Record]:
        if day not in self._days:
            path = self.data_dir / day_path(day)
            self._days[day] = parse_day_csv(path.read_text("utf-8")) if path.exists() else []
        return self._days[day]

    def _status(self) -> dict:
        path = self.data_dir / STATUS_PATH
        return json.loads(path.read_text("utf-8")) if path.exists() else {}

    def _save(self, status: dict) -> None:
        for day in sorted(self._dirty):
            path = self.data_dir / day_path(day)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_day_csv(self._days[day]), "utf-8")
        path = self.data_dir / STATUS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", "utf-8")

    # -- run
    def run(self, now: datetime | None = None) -> tuple[RunReport, int]:
        now = now or datetime.now(UTC)
        report = RunReport()
        status = self._status()
        labels = due_labels(now, self.lookback_hours)
        oldest = labels[-1]
        misses = {
            k: v for k, v in status.get("missing_attempts", {}).items()
            if datetime.fromisoformat(k) >= oldest
        }
        stored = {
            r.period_label_utc
            for day in {lb.date() for lb in labels}
            for r in self._load(day)
        }
        wanted = [
            lb for lb in labels
            if lb not in stored
            and (lb == labels[0] or misses.get(lb.isoformat(), 0) < self.missing_attempts)
        ][: self.max_requests]

        if wanted:
            with self.client_factory() as client, ThreadPoolExecutor(self.concurrency) as pool:
                results = list(pool.map(lambda lb: (lb, fetch(client, self.url(lb))), wanted))
            for label, result in results:
                report.requested += 1
                self._apply(label, result, now, report, misses)

        latest = max(
            (r.period_label_utc for d in self._days.values() for r in d), default=None
        )
        if latest is None and status.get("latest_label_utc"):
            latest = datetime.fromisoformat(status["latest_label_utc"])
        ok = report.integrity_error is None and (report.failures == 0 or report.inserted > 0)
        status.update(
            last_run_at=now.isoformat(),
            last_run=dict(
                requested=report.requested,
                inserted=report.inserted,
                revised=report.revised,
                not_published=report.not_published,
                failures=report.failures,
                failure_kinds=report.failure_kinds,
                integrity_error=report.integrity_error,
            ),
            lookback_hours=self.lookback_hours,
            parser_version=PARSER_VERSION,
            missing_attempts=dict(sorted(misses.items())),
        )
        if latest is not None:
            status["latest_label_utc"] = latest.isoformat()
        if ok:
            status["last_success_at"] = now.isoformat()
        self._save(status)

        if report.integrity_error:
            return report, 1
        stale = latest is None or now - latest > timedelta(hours=float(
            os.environ.get("WINDCAST_ALERT_AFTER_HOURS", "6")))
        if report.failures and report.inserted == 0 and stale:
            return report, 2
        return report, 0

    def url(self, label: datetime) -> str:
        return self.base_url + export_file_name(label)

    def _apply(
        self, label: datetime, result: FetchResult, now: datetime, report: RunReport, misses: dict
    ) -> None:
        if result.kind is FetchKind.NOT_PUBLISHED:
            report.not_published += 1
            misses[label.isoformat()] = misses.get(label.isoformat(), 0) + 1
            return
        if result.kind is not FetchKind.OK:
            report.failures += 1
            report.failure_kinds[result.kind.value] = report.failure_kinds.get(result.kind.value, 0) + 1
            return
        try:
            reading = parse_wind_export(result.body)
            if reading.period_label_utc != label:
                raise GseParseError(f"label mismatch: {reading.period_label_utc} != {label}")
            if reading.period_label_utc > now + FUTURE_TOLERANCE:
                raise GseParseError("future label")
        except GseParseError as exc:
            report.integrity_error = f"{exc.code}: {label.isoformat()}"
            print(f"refused {self.url(label)}: {exc}", file=sys.stderr)
            return
        record = Record(
            period_label_utc=reading.period_label_utc,
            period_label_local=reading.period_label_local,
            value_mw=reading.value_mw,
            quality=reading.quality,
            retrieved_at_utc=now,
            payload_sha256=hashlib.sha256(result.body).hexdigest(),
            parser_version=PARSER_VERSION,
        )
        day = label.date()
        merged, outcome = merge(self._load(day), record)
        if outcome != "unchanged":
            self._days[day] = merged
            self._dirty.add(day)
            report.inserted += outcome == "inserted"
            report.revised += outcome == "revised"
        misses.pop(label.isoformat(), None)


WEATHER_DIR = "weather"


def collect_weather(data_dir: Path, client_factory: Callable[[], httpx.Client], now: datetime) -> tuple[dict, int]:
    """Stores validated Open-Meteo payloads as a second path for the app (shared cloud IPs hit the
    provider's per-IP limits). Forecast: once per new model run, run time checked before and after.
    ERA5: once per UTC day. Returns (status, exit code: 1 only for a schema refusal)."""
    import data as src  # same validation as the app's live path
    from app.ingestion.openmeteo import OpenMeteoError

    wdir = data_dir / WEATHER_DIR
    wdir.mkdir(parents=True, exist_ok=True)

    def load(name: str) -> dict:
        path = wdir / name
        return json.loads(path.read_text("utf-8")) if path.exists() else {}

    status: dict = {"last_run_at": now.isoformat()}
    code = 0
    with client_factory() as client:
        def get(url: str) -> bytes:
            result = fetch(client, url, expect="json")
            if result.kind is not FetchKind.OK:
                raise src.SourceError(result.kind.value)
            return result.body

        for product in ("forecast", "era5"):
            try:
                meta = load(f"{product}_meta.json")
                if product == "forecast":
                    murl = src.meta_url(src.WEATHER_BASE, src.FORECAST.meta_model)
                    run = src.parse_run_time(get(murl))
                    if run > now:
                        raise src.SourceError("future_model_run")
                    if meta.get("run") == run.isoformat():
                        status[product] = "unchanged"
                        continue
                    url = src.forecast_url(src.WEATHER_BASE, src.SITES, 4)
                    body = get(url)
                    if src.parse_run_time(get(murl)) != run:
                        raise src.SourceError("model_run_changed_during_fetch")
                    packet = src.forecast_packet(body, run, now, url, "collector")
                    new_meta = dict(run=run.isoformat(), retrieved=now.isoformat(), url=url, sha256=packet["sha256"])
                else:
                    if meta.get("retrieved", "")[:10] == now.date().isoformat():
                        status[product] = "unchanged"
                        continue
                    url = src.era5_url(now)
                    body = get(url)
                    packet = src.archive_packet(body, now, url, "collector")
                    new_meta = dict(retrieved=now.isoformat(), url=url, sha256=packet["sha256"])
                (wdir / f"{product}.json").write_bytes(body)
                (wdir / f"{product}_meta.json").write_text(json.dumps(new_meta, indent=2) + "\n", "utf-8")
                status[product] = "updated"
            except OpenMeteoError as exc:  # schema drift: refuse and fail visibly
                status[product] = f"refused: {exc.code}"
                code = 1
            except (src.SourceError, ValueError, httpx.HTTPError) as exc:  # transient: keep old copy
                status[product] = f"failed: {getattr(exc, 'code', type(exc).__name__)}"
    (wdir / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", "utf-8")
    return status, code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data-dir", type=Path, required=True)
    p.add_argument("--lookback-hours", type=float, default=12)
    p.add_argument("--max-requests", type=int, default=300)
    p.add_argument("--weather", action="store_true", help="also store Open-Meteo forecast/ERA5 copies")
    args = p.parse_args(argv)
    headers = {"Accept": "application/xml, text/xml"}
    if ua := os.environ.get("WINDCAST_GSE_USER_AGENT"):
        headers["User-Agent"] = ua
    collector = Collector(
        args.data_dir,
        lambda: httpx.Client(timeout=httpx.Timeout(15.0), headers=headers, follow_redirects=False),
        lookback_hours=args.lookback_hours,
        max_requests=args.max_requests,
    )
    report, code = collector.run()
    print(json.dumps(report.__dict__, sort_keys=True))
    if args.weather:
        wheaders = {"Accept": "application/json", **({"User-Agent": ua} if ua else {})}
        wstatus, wcode = collect_weather(
            args.data_dir,
            lambda: httpx.Client(timeout=httpx.Timeout(20.0), headers=wheaders, follow_redirects=False),
            datetime.now(UTC),
        )
        print(json.dumps(wstatus, sort_keys=True))
        code = code or wcode
    return code


if __name__ == "__main__":
    raise SystemExit(main())
