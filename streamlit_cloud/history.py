"""Reads the durable GSE history (``data`` branch) for the app, with a shared, bounded cache."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import httpx

from store import Record, StoreFormatError, day_path, parse_day_csv

DATA_BASE = "https://raw.githubusercontent.com/GiorgiKhorbaladze/Georgia-WindCast/data/"
RECENT_TTL = timedelta(minutes=2)  # today/yesterday change with every collector run
ARCHIVE_TTL = timedelta(hours=6)  # older days only change on a rare GSE revision
STATUS_PATH = "status/gse_collector.json"


class HistoryReader:
    def __init__(
        self, client_factory: Callable[[], httpx.Client], base_url: str = DATA_BASE
    ) -> None:
        self._client_factory = client_factory
        self._base = base_url.rstrip("/") + "/"
        self._lock = threading.Lock()
        self._days: dict[date, tuple[datetime, list[Record]]] = {}
        self._status: tuple[datetime, dict | None] | None = None
        self._weather: tuple[datetime, dict | None, dict | None] | None = None
        self.error: str | None = None

    def _get(self, client: httpx.Client, path: str) -> str | None:
        resp = client.get(self._base + path)
        if resp.status_code == 404:
            return None  # nothing collected for that day (or before the first run)
        resp.raise_for_status()
        return resp.text

    def records(self, start: datetime, end: datetime, now: datetime) -> list[Record]:
        days = [start.date() + timedelta(days=i) for i in range((end.date() - start.date()).days + 1)]
        with self._lock:
            due = [
                d for d in days
                if d not in self._days
                or now - self._days[d][0] >= (RECENT_TTL if d >= now.date() - timedelta(days=1) else ARCHIVE_TTL)
            ]
            if due:
                try:
                    with self._client_factory() as client:
                        for d in due:
                            text = self._get(client, day_path(d))
                            self._days[d] = (now, parse_day_csv(text) if text else [])
                    self.error = None
                except (httpx.HTTPError, StoreFormatError) as exc:  # keep the last good copies
                    self.error = getattr(exc, "code", "history_unavailable")
            out = [
                r for d in days if d in self._days for r in self._days[d][1]
                if start <= r.period_label_utc <= end
            ]
        return sorted(out, key=lambda r: r.period_label_utc)

    def status(self, now: datetime) -> dict | None:
        with self._lock:
            if self._status is None or now - self._status[0] >= RECENT_TTL:
                try:
                    with self._client_factory() as client:
                        text = self._get(client, STATUS_PATH)
                    self._status = (now, json.loads(text) if text else None)
                except (httpx.HTTPError, ValueError):
                    self._status = (now, self._status[1] if self._status else None)
            return self._status[1]


    def weather(self, now: datetime) -> tuple[dict | None, dict | None]:
        """Collector's stored Open-Meteo copies, validated exactly like live responses."""
        import data as src  # local import: data adds backend/ to sys.path

        with self._lock:
            if self._weather is None or now - self._weather[0] >= timedelta(minutes=10):
                old = self._weather
                packets = [old[1], old[2]] if old else [None, None]
                for index, product in enumerate(("forecast", "era5")):
                    try:
                        with self._client_factory() as client:
                            meta = self._get(client, f"weather/{product}_meta.json")
                            if not meta:
                                continue
                            m = json.loads(meta)
                            digest = m["sha256"]
                            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                                raise ValueError("invalid payload hash")
                            # New manifests name an immutable content-addressed payload.
                            # Legacy manifests remain supported, but must also match byte-for-byte.
                            path = f"weather/payloads/{digest}.json" if m.get("content_addressed") else f"weather/{product}.json"
                            response = client.get(self._base + path)
                            response.raise_for_status()
                            body = response.content
                            if hashlib.sha256(body).hexdigest() != digest:
                                raise ValueError("weather payload hash mismatch")
                            retrieved = datetime.fromisoformat(m["retrieved"])
                            if retrieved.utcoffset() is None or retrieved > now:
                                raise ValueError("invalid retrieval time")
                            if product == "forecast":
                                run = datetime.fromisoformat(m["run"])
                                if run.utcoffset() is None or run > retrieved:
                                    raise ValueError("invalid model run")
                                packet = src.forecast_packet(body, run, retrieved, m["url"], "collector")
                                key = "run"
                            else:
                                packet = src.archive_packet(body, retrieved, m["url"], "collector")
                                key = "retrieved"
                            if packets[index] is None or packet[key] >= packets[index][key]:
                                packets[index] = packet
                    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                        pass  # keep this product's last validated copy independently
                forecast, archive = packets
                self._weather = (now, forecast, archive)
            return self._weather[1], self._weather[2]


def collector_age(status: dict | None, now: datetime) -> timedelta | None:
    if not status or not status.get("last_success_at"):
        return None
    return now - datetime.fromisoformat(status["last_success_at"]).astimezone(UTC)
