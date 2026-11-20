"""Scheduled GSE collector for the Streamlit edition (run by .github/workflows/collect-gse.yml).

Each run backfills every 3-minute period of the last ``--lookback-hours`` that is not yet stored,
newest first. GSE keeps published files for at least 48 h (checked 2026-11-16, docs/sources/gse.md),
but automatic recovery is bounded by the lookback and request budget; gaps remain possible. Periods GSE never published stay gaps: after ``--missing-attempts`` runs with 404
they are no longer requested.

Exit codes: 0 ok (including "nothing new" and transient source errors); 1 data-integrity refusal
(schema drift, label mismatch, future label) so the workflow fails visibly; 2 no reading newer
than WINDCAST_ALERT_AFTER_HOURS (default 6), including all-404 responses.
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
from balance import BALANCE_PARSER_VERSION, parse_balance  # noqa: E402
from store import (  # noqa: E402
    BalanceRecord,
    Record,
    balance_day_path,
    day_path,
    merge,
    merge_balance,
    parse_balance_csv,
    parse_day_csv,
    render_balance_csv,
    render_day_csv,
)

GSE_BASE = "https://admin.gse.com.ge/storage/uploads/fact/"
PERIOD = timedelta(minutes=3)
PUBLICATION_LAG = timedelta(seconds=75)
FUTURE_TOLERANCE = timedelta(seconds=60)
STATUS_PATH = "status/gse_collector.json"
REVALIDATE_PER_RUN = 4
# Adaptive catch-up: if the last stored label is older than the normal lookback (GitHub skipped or
# delayed runs), the run widens its window up to this limit. GSE files were observed to stay available
# for at least 14 days (2026-11-16); 96 h covers multi-day gaps in GitHub's best-effort schedule
# (seen 17.11.2026: 3 scheduled runs in about 20 h). The deep backfill only walks backwards from the
# oldest stored period; this window recovers recent gaps and the bounded gap repair below older ones.
MAX_AUTO_LOOKBACK_HOURS = 96
# Deep backfill: a small number of extra requests per run walk backwards from the oldest stored
# period until DEEP_HORIZON_DAYS or a full day of 404s (GSE retention end). Temporary extra load,
# about DEEP_PER_RUN x 96 requests/day until done; each deep period is tried once.
DEEP_PER_RUN = 20
DEEP_HORIZON_DAYS = 30
# Gap repair: periods between the oldest stored label and the recovery window that lack wind or
# balance (e.g. collected before the balance parser existed, or skipped by more than 96 h) are
# requested again, newest first, at most deep_per_run per run. A 404 does not prove that a period will
# never be published, so it is rechecked with growing delays (GAP_RETRY_DELAYS after the 1st, 2nd, ...
# 404); after the last delay the period is left as a gap. Worst case per unpublished period:
# 1 + len(GAP_RETRY_DELAYS) requests over about 4 days, always inside the per-run bound.
GAP_STATUS_KEY = "gap_repair"
# Deep backfill and gap repair are extra load on GSE. Their per-run budgets were sized for roughly
# hourly runs; with an external 15-minute trigger (cron-job.org, 19.11.2026) that quadrupled the
# daily volume (~4,700 requests/day vs the documented 500-1000/day envelope). They now run at most
# once per EXTRA_INTERVAL; the normal recovery window is unaffected and runs every time.
EXTRA_INTERVAL = timedelta(minutes=55)
EXTRA_STATUS_KEY = "extra_last_run_at"
GAP_RETRY_DELAYS = (timedelta(hours=1), timedelta(hours=6), timedelta(hours=24), timedelta(hours=72))


def due_labels(now: datetime, hours: float) -> list[datetime]:
    newest = (now - PUBLICATION_LAG).replace(second=0, microsecond=0)
    newest -= timedelta(minutes=newest.minute % 3)
    return [newest - i * PERIOD for i in range(int(hours * 20))]


@dataclass
class RunReport:
    requested: int = 0
    acquired: int = 0
    inserted: int = 0
    revised: int = 0
    not_published: int = 0
    failures: int = 0
    integrity_error: str | None = None
    failure_kinds: dict[str, int] = field(default_factory=dict)
    lookback_used_hours: float = 0.0
    backfilled: int = 0  # inserted periods older than 1 h (recovered rather than fresh)
    deep_requested: int = 0
    deep_inserted: int = 0
    balance_stored: int = 0
    balance_errors: int = 0
    repair_requested: int = 0
    repair_inserted: int = 0  # wind periods inserted by gap repair (balance-only fills count in balance_stored)


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
        deep_per_run: int = DEEP_PER_RUN,
    ) -> None:
        self.deep_per_run = deep_per_run
        self.data_dir = data_dir
        self.client_factory = client_factory
        self.base_url = base_url.rstrip("/") + "/"
        self.lookback_hours = lookback_hours
        self.max_requests = max_requests
        self.missing_attempts = missing_attempts
        self.concurrency = concurrency
        self._days: dict[date, list[Record]] = {}
        self._dirty: set[date] = set()
        self._bdays: dict[date, list[BalanceRecord]] = {}
        self._bdirty: set[date] = set()

    # -- storage
    def _load(self, day: date) -> list[Record]:
        if day not in self._days:
            path = self.data_dir / day_path(day)
            self._days[day] = parse_day_csv(path.read_text("utf-8")) if path.exists() else []
        return self._days[day]

    def _load_balance(self, day: date) -> list[BalanceRecord]:
        if day not in self._bdays:
            path = self.data_dir / balance_day_path(day)
            self._bdays[day] = parse_balance_csv(path.read_text("utf-8")) if path.exists() else []
        return self._bdays[day]

    def _has_both(self, label: datetime) -> bool:
        return (any(r.period_label_utc == label for r in self._load(label.date()))
                and any(r.period_label_utc == label and r.import_mw is not None
                        for r in self._load_balance(label.date())))

    def _status(self) -> dict:
        path = self.data_dir / STATUS_PATH
        return json.loads(path.read_text("utf-8")) if path.exists() else {}

    def _save(self, status: dict) -> None:
        for day in sorted(self._dirty):
            path = self.data_dir / day_path(day)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_day_csv(self._days[day]), "utf-8")
        for day in sorted(self._bdirty):
            path = self.data_dir / balance_day_path(day)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_balance_csv(self._bdays[day]), "utf-8")
        path = self.data_dir / STATUS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", "utf-8")

    # -- run
    def run(self, now: datetime | None = None) -> tuple[RunReport, int]:
        now = now or datetime.now(UTC)
        report = RunReport()
        status = self._status()
        lookback = self.lookback_hours
        if status.get("latest_label_utc"):
            behind = (now - datetime.fromisoformat(status["latest_label_utc"])).total_seconds() / 3600
            if behind > lookback:  # skipped or delayed runs: widen the window, bounded
                lookback = min(float(MAX_AUTO_LOOKBACK_HOURS), max(lookback, behind + 1))
        report.lookback_used_hours = lookback
        labels = due_labels(now, lookback)
        oldest = labels[-1]
        misses = {
            k: v for k, v in status.get("missing_attempts", {}).items()
            if datetime.fromisoformat(k) >= oldest
        }
        stored = {
            r.period_label_utc: r
            for day in {lb.date() for lb in labels}
            for r in self._load(day)
        }
        bstored = {  # rows without gross import/export (older parser) count as missing
            r.period_label_utc
            for day in {lb.date() for lb in labels}
            for r in self._load_balance(day) if r.import_mw is not None
        }
        checked = {
            k: v for k, v in status.get("revalidated_at", {}).items()
            if datetime.fromisoformat(k) >= oldest
        }
        # Bounded revision discovery (published files are cache-immutable per GSE headers, so this is
        # a safety net, not a re-crawl): only rows still worth rechecking - non-ACT codes, or labels
        # from the last 2 hours (one recheck about an hour after collection) - each at most hourly, at most REVALIDATE_PER_RUN per run, non-ACT and
        # newest first. Keeps steady-state load within the production worker's envelope
        # (docs/sources/gse.md: about 500-1000 requests/day); simulated: <= 480 + 4 x 96 per day.
        revisions = sorted(
            (lb for lb in labels if lb in stored
             and (stored[lb].quality != "ACT" or now - lb <= timedelta(hours=2))
             and now - datetime.fromisoformat(checked.get(lb.isoformat(), stored[lb].retrieved_at_utc.isoformat())) >= timedelta(hours=1)),
            key=lambda lb: (stored[lb].quality == "ACT", -lb.timestamp()),
        )[:min(REVALIDATE_PER_RUN, self.max_requests // 4)]
        wanted = [
            lb for lb in labels
            if (lb not in stored or lb not in bstored)
            and (lb == labels[0] or misses.get(lb.isoformat(), 0) < self.missing_attempts)
        ][: self.max_requests - len(revisions)] + revisions

        if wanted:
            with self.client_factory() as client, ThreadPoolExecutor(self.concurrency) as pool:
                results = list(pool.map(lambda lb: (lb, fetch(client, self.url(lb))), wanted))
            for label, result in results:
                report.requested += 1
                before = report.inserted
                self._apply(label, result, now, report, misses)
                checked[label.isoformat()] = now.isoformat()
                if report.inserted > before and now - label > timedelta(hours=1):
                    report.backfilled += 1

        deep = status.get("deep_backfill", {})
        gaps = status.get(GAP_STATUS_KEY, {})
        last_extra = status.get(EXTRA_STATUS_KEY)
        extra_due = last_extra is None or now - datetime.fromisoformat(last_extra) >= EXTRA_INTERVAL
        if extra_due and self.deep_per_run and report.failures == 0 and report.integrity_error is None:
            status[EXTRA_STATUS_KEY] = now.isoformat()
        else:
            extra_due = False
        if extra_due:
            gaps = self._repair_gaps(now, labels[-1], deep, gaps, report)
        if extra_due and not deep.get("done") and report.failures == 0 and report.integrity_error is None:
            deep = self._deep_backfill(now, labels[-1], deep, report)

        latest = max(
            (r.period_label_utc for d in self._days.values() for r in d), default=None
        )
        if latest is None and status.get("latest_label_utc"):
            latest = datetime.fromisoformat(status["latest_label_utc"])
        ok = report.integrity_error is None and report.acquired > 0
        status.update(
            last_run_at=now.isoformat(),
            last_run=dict(
                requested=report.requested,
                acquired=report.acquired,
                inserted=report.inserted,
                revised=report.revised,
                not_published=report.not_published,
                failures=report.failures,
                failure_kinds=report.failure_kinds,
                integrity_error=report.integrity_error,
                lookback_used_hours=report.lookback_used_hours,
                backfilled=report.backfilled,
                deep_requested=report.deep_requested,
                deep_inserted=report.deep_inserted,
                balance_stored=report.balance_stored,
                balance_errors=report.balance_errors,
                repair_requested=report.repair_requested,
                repair_inserted=report.repair_inserted,
            ),
            lookback_hours=self.lookback_hours,
            deep_backfill=deep,
            **{GAP_STATUS_KEY: gaps},
            parser_version=PARSER_VERSION,
            revalidated_at=checked,
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
        if stale:
            return report, 2
        return report, 0

    def _repair_gaps(self, now: datetime, window_start: datetime, deep: dict, gaps: dict, report: RunReport) -> dict:
        """Re-request stored-range periods older than the window that lack wind or balance."""
        horizon = now - timedelta(days=DEEP_HORIZON_DAYS)
        lower = max(horizon, datetime.fromisoformat(deep["cursor"])) if deep.get("cursor") else window_start
        attempts = self._gap_attempts(gaps, now, horizon)

        def due(label: datetime) -> bool:
            a = attempts.get(label.isoformat())
            if a is None:
                return True
            n = int(a["n"])
            return n <= len(GAP_RETRY_DELAYS) and now - datetime.fromisoformat(a["last"]) >= GAP_RETRY_DELAYS[n - 1]

        todo: list[datetime] = []
        if lower < window_start:
            day = window_start.date()
            while day >= lower.date() and len(todo) < self.deep_per_run:
                wind = {r.period_label_utc for r in self._load(day)}
                bal = {r.period_label_utc for r in self._load_balance(day) if r.import_mw is not None}
                label = min(window_start - PERIOD, datetime.combine(day, datetime.max.time(), UTC).replace(
                    second=0, microsecond=0, minute=57))
                start = max(lower, datetime.combine(day, datetime.min.time(), UTC))
                while label >= start and len(todo) < self.deep_per_run:
                    if (label not in wind or label not in bal) and due(label):
                        todo.append(label)
                    label -= PERIOD
                day -= timedelta(days=1)
        if todo:
            with self.client_factory() as client, ThreadPoolExecutor(self.concurrency) as pool:
                results = list(pool.map(lambda lb: (lb, fetch(client, self.url(lb))), todo))
            for lb, result in results:
                report.repair_requested += 1
                if result.kind is FetchKind.NOT_PUBLISHED:
                    prev = attempts.get(lb.isoformat(), {"n": 0})
                    attempts[lb.isoformat()] = {"n": int(prev["n"]) + 1, "last": now.isoformat()}
                    continue
                if result.kind is not FetchKind.OK:
                    report.failures += 1
                    break
                before = report.inserted
                self._apply(lb, result, now, report, {})
                if report.integrity_error:
                    break
                attempts.pop(lb.isoformat(), None)  # published after all: no longer a gap
                report.repair_inserted += report.inserted - before
                report.backfilled += report.inserted - before
        return {"attempts_404": dict(sorted(attempts.items())), "updated_at": now.isoformat()}

    @staticmethod
    def _gap_attempts(gaps: dict, now: datetime, horizon: datetime) -> dict:
        """404 history per label; migrates the earlier one-shot list (counted as one 404 at updated_at)."""
        attempts = {k: dict(v) for k, v in gaps.get("attempts_404", {}).items()}
        legacy_at = gaps.get("updated_at", now.isoformat())
        for k in gaps.get("not_published", []):
            attempts.setdefault(k, {"n": 1, "last": legacy_at})
        return {k: v for k, v in attempts.items() if datetime.fromisoformat(k) >= horizon}

    def _deep_backfill(self, now: datetime, window_start: datetime, deep: dict, report: RunReport) -> dict:
        """Walk backwards from the cursor, DEEP_PER_RUN periods per run, each tried once."""
        horizon = now - timedelta(days=DEEP_HORIZON_DAYS)
        cursor = datetime.fromisoformat(deep["cursor"]) if deep.get("cursor") else window_start
        streak = int(deep.get("consecutive_404", 0))
        todo: list[datetime] = []
        label = cursor - PERIOD
        while len(todo) < self.deep_per_run and label >= horizon:
            if not self._has_both(label):
                todo.append(label)
            label -= PERIOD
        processed = cursor if not todo else None
        if todo:
            with self.client_factory() as client, ThreadPoolExecutor(self.concurrency) as pool:
                results = list(pool.map(lambda lb: (lb, fetch(client, self.url(lb))), todo))
            for lb, result in results:  # newest first: the streak counts consecutive older 404s
                report.deep_requested += 1
                if result.kind is FetchKind.NOT_PUBLISHED:
                    streak += 1
                    processed = lb
                    continue
                if result.kind is not FetchKind.OK:
                    report.failures += 1
                    break
                before = report.inserted
                self._apply(lb, result, now, report, {})
                if report.integrity_error:
                    break
                report.deep_inserted += report.inserted - before
                report.backfilled += report.inserted - before
                streak = 0
                processed = lb
        # Only periods actually processed move the cursor; unfetched ones are retried next run.
        cursor = processed if processed is not None else cursor
        if not todo:
            cursor = max(label, horizon)
        done = cursor <= horizon or streak >= 480  # horizon reached or a full day of 404s
        return dict(cursor=cursor.isoformat(), consecutive_404=streak, done=done,
                    horizon_days=DEEP_HORIZON_DAYS, updated_at=now.isoformat())

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
        report.acquired += 1
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
        self._apply_balance(label, result.body, record.payload_sha256, now, report)

    def _apply_balance(self, label: datetime, body: bytes, digest: str, now: datetime, report: RunReport) -> None:
        """System balance from the same payload. A refusal here never blocks the wind record."""
        try:
            b_label, b = parse_balance(body)
            if b_label != label:
                raise GseParseError("balance label mismatch")
        except GseParseError as exc:
            report.balance_errors += 1
            print(f"balance refused {self.url(label)}: {exc}", file=sys.stderr)
            return
        rec = BalanceRecord(label, b.period_label_local, b.hydro, b.thermal, b.wind, b.solar, b.generation,
                            b.consumption, b.quality, now, digest, BALANCE_PARSER_VERSION,
                            import_mw=b.imports, export_mw=b.exports)
        merged, changed = merge_balance(self._load_balance(label.date()), rec)
        if changed:
            self._bdays[label.date()] = merged
            self._bdirty.add(label.date())
            report.balance_stored += 1


WEATHER_DIR = "weather"
HIST_FORECAST_DAYS = 31  # training window for the MW model (past ICON forecasts)
RUN_ARCHIVE_DAYS = 60  # forecast runs listed for the accuracy evaluation


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

        for product in ("forecast", "era5", "hist_forecast"):
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
                elif product == "era5":
                    if meta.get("retrieved", "")[:10] == now.date().isoformat():
                        status[product] = "unchanged"
                        continue
                    url = src.era5_url(now)
                    body = get(url)
                    packet = src.archive_packet(body, now, url, "collector")
                    new_meta = dict(retrieved=now.isoformat(), url=url, sha256=packet["sha256"])
                else:  # past ICON forecasts (best-match archive) for MW model training, daily
                    if meta.get("retrieved", "")[:10] == now.date().isoformat():
                        status[product] = "unchanged"
                        continue
                    end = now.date() - timedelta(days=1)
                    start = end - timedelta(days=HIST_FORECAST_DAYS - 1)
                    url = src.hist_forecast_url(start, end)
                    body = get(url)
                    src.hist_forecast_packet(body, now, url)  # validation only
                    new_meta = dict(retrieved=now.isoformat(), url=url, start=start.isoformat(),
                                    end=end.isoformat(), sha256=hashlib.sha256(body).hexdigest())
                payloads = wdir / "payloads"
                payloads.mkdir(exist_ok=True)
                (payloads / f"{new_meta['sha256']}.json").write_bytes(body)
                new_meta["content_addressed"] = True
                (wdir / f"{product}.json").write_bytes(body)
                (wdir / f"{product}_meta.json").write_text(json.dumps(new_meta, indent=2) + "\n", "utf-8")
                if product == "forecast":  # archive index for the accuracy evaluation
                    manifest = load("forecast_runs.json").get("runs", [])
                    manifest = [m for m in manifest if m["run"] != new_meta["run"]
                                and datetime.fromisoformat(m["run"]) >= now - timedelta(days=RUN_ARCHIVE_DAYS)]
                    manifest.append(dict(run=new_meta["run"], sha256=new_meta["sha256"], retrieved=new_meta["retrieved"]))
                    (wdir / "forecast_runs.json").write_text(
                        json.dumps({"runs": sorted(manifest, key=lambda m: m["run"])}, indent=2) + "\n", "utf-8")
                status[product] = "updated"
            except OpenMeteoError as exc:  # schema drift: refuse; fail visibly for the live products
                status[product] = f"refused: {exc.code}"
                if product != "hist_forecast":  # training archive: format not yet verified live
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
