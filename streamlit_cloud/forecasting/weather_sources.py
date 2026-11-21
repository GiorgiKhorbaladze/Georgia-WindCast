"""Independent NWP sources for the forecasting models (Issue #57, owner decision 21.11.2026).

Sources (no API key, no cost; AWS Open Data mirrors of the official model output):

* ``gfs`` - NOAA GFS 0.25 deg, ``noaa-gfs-bdp-pds`` bucket (``.idx`` byte index per file).
* ``ecmwf`` - ECMWF IFS open data 0.25 deg (CC BY 4.0), ``ecmwf-forecasts`` bucket (JSON index).

Only the needed GRIB2 messages are downloaded (HTTP Range from the index offsets), decoded with
ecCodes and read at the grid point nearest to each of forecasting.features.POINTS. The result is
the same long table as weather_points.py (point, valid_utc, variable, value), so all sources can
be compared with the same models. Open-Meteo ICON stays as it is; these do not replace it.

As-of: each run records its initialisation time, the S3 LastModified of every file used (when it
was published) and the time it was retrieved here. A model issued at T may use a run only if
run <= T and retrieved <= T. Units are converted to the canonical units of features.UNITS;
values outside features.RANGES are refused. Nothing is interpolated in time: a source with
3-hourly steps has values only at those hours.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from forecasting.features import POINTS, RANGES, UNITS

ROOT = Path("weather") / "sources"
STEPS = tuple(range(0, 73, 3))  # native 3-hourly steps to 72 h for both sources
CANONICAL = ("temperature_2m", "relative_humidity_2m", "pressure_msl", "surface_pressure", "precipitation",
             "cloud_cover", "wind_speed_10m", "wind_direction_10m", "wind_speed_100m", "wind_direction_100m",
             "wind_gusts_10m")
UNITS_EXT = {**UNITS, "wind_speed_100m": "m/s", "wind_direction_100m": "°"}


class SourceError(ValueError):
    pass


@dataclass
class Message:
    key: str  # canonical field id, e.g. "u10", "tp"
    url: str
    offset: int
    length: int
    step: int
    period: tuple[int, int] | None = None  # accumulation period (start_h, end_h) when relevant


@dataclass
class Http:
    """Range GET with retry/backoff (S3 answers 503 SlowDown under load)."""

    get: Callable[[str, dict], tuple[int, bytes, dict]]
    sleep: Callable[[float], None] = time.sleep
    requests: int = 0
    bytes: int = 0

    def fetch(self, url: str, rng: tuple[int, int] | None = None) -> tuple[bytes, dict]:
        headers = {"Range": f"bytes={rng[0]}-{rng[1]}"} if rng else {}
        for attempt in range(8):
            status, body, hdrs = self.get(url, headers)
            self.requests += 1
            if status in (200, 206):
                self.bytes += len(body)
                return body, hdrs
            if status in (429, 500, 503):
                self.sleep(min(30, 2 ** attempt))  # S3 SlowDown: back off up to ~2 minutes in total
                continue
            raise SourceError(f"http {status} for {url}")
        raise SourceError(f"gave up after retries: {url}")


# --- GFS ------------------------------------------------------------------------------------
GFS_BASE = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
GFS_FIELDS = {  # idx "VAR:level" -> canonical field id
    "PRMSL:mean sea level": "msl", "PRES:surface": "sp", "TMP:2 m above ground": "t2",
    "RH:2 m above ground": "rh2", "UGRD:10 m above ground": "u10", "VGRD:10 m above ground": "v10",
    "UGRD:100 m above ground": "u100", "VGRD:100 m above ground": "v100", "GUST:surface": "gust",
    "APCP:surface": "tp", "TCDC:entire atmosphere": "tcc",
}


def gfs_file(run: datetime, step: int) -> str:
    return f"{GFS_BASE}/gfs.{run:%Y%m%d}/{run:%H}/atmos/gfs.t{run:%H}z.pgrb2.0p25.f{step:03d}"


def parse_gfs_idx(text: str, url: str, step: int, total_size: int | None = None) -> list[Message]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    rows = [ln.split(":") for ln in lines]
    out = []
    for i, r in enumerate(rows):
        var, level, desc = r[3], r[4], r[5]
        key = GFS_FIELDS.get(f"{var}:{level}")
        if key is None:
            continue
        period = None
        if key == "tp":
            m = re.match(r"(\d+)-(\d+) hour acc", desc)
            if not m:
                continue
            period = (int(m.group(1)), int(m.group(2)))
        elif key == "tcc" and "ave" in desc:
            continue  # instantaneous cloud cover only
        start = int(r[1])
        end = int(rows[i + 1][1]) - 1 if i + 1 < len(rows) else (total_size - 1 if total_size else None)
        if end is None:
            raise SourceError("last idx record needs the file size")
        out.append(Message(key, url, start, end - start + 1, step, period))
    return out


# --- ECMWF ----------------------------------------------------------------------------------
ECMWF_BASE = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"
ECMWF_FIELDS = {"msl": "msl", "sp": "sp", "2t": "t2", "2d": "td2", "10u": "u10", "10v": "v10", "100u": "u100",
                "100v": "v100", "10fg": "gust", "tp": "tp", "tcc": "tcc"}


def ecmwf_file(run: datetime, step: int, ext: str) -> str:
    return (f"{ECMWF_BASE}/{run:%Y%m%d}/{run:%H}z/ifs/0p25/oper/"
            f"{run:%Y%m%d%H}0000-{step}h-oper-fc.{ext}")


def parse_ecmwf_index(text: str, url: str, step: int) -> list[Message]:
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        key = ECMWF_FIELDS.get(d.get("param", ""))
        if key is None or d.get("levtype") != "sfc":
            continue
        period = (0, step) if key == "tp" else None  # IFS tp accumulates from the run start
        out.append(Message(key, url, int(d["_offset"]), int(d["_length"]), step, period))
    return out


# --- decoding and normalisation -------------------------------------------------------------
def decode_points(grib: bytes) -> list[tuple[float, float, float]]:
    """(value, grid_lat, grid_lon) at the grid point nearest to each of POINTS (ecCodes)."""
    import eccodes

    gid = eccodes.codes_new_from_message(grib)
    try:
        out = []
        for p in POINTS:
            near = eccodes.codes_grib_find_nearest(gid, p.lat, p.lon)[0]
            out.append((float(near["value"]), float(near["lat"]), float(near["lon"])))
        missing = eccodes.codes_get(gid, "missingValue") if eccodes.codes_is_defined(gid, "missingValue") else None
    finally:
        eccodes.codes_release(gid)
    return [(math.nan if missing is not None and v == missing else v, la, lo) for v, la, lo in out]


def rh_from_dewpoint(t_c: float, td_c: float) -> float:
    """Relative humidity (%) from 2 m temperature and dew point (Magnus, over water)."""
    e = lambda t: math.exp(17.625 * t / (t + 243.04))  # noqa: E731
    return max(0.0, min(100.0, 100.0 * e(td_c) / e(t_c)))


def wind(u: float, v: float) -> tuple[float, float]:
    """Speed (m/s) and meteorological direction (degrees the wind blows FROM)."""
    return math.hypot(u, v), (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0


# Largest negative step change accepted as GRIB packing noise, in native units (GFS kg/m2 = mm,
# IFS metres). Anything more negative is an inconsistent source, never clipped to dry weather.
PACKING_TOL = {"gfs": 0.05, "ecmwf": 0.00005}


def interval_precip(acc: dict[tuple[int, int], float], steps: list[int], tol: float = 0.05,
                    flags: list | None = None) -> dict[int, float]:
    """Precipitation in (previous step, step] from accumulations over (start, end] periods.

    Missing or non-finite inputs give NO value (never 0). A difference below -tol is reported in
    ``flags`` and gives no value; only -tol <= v < 0 (packing noise) is set to 0."""
    def ok(v):
        return v is not None and math.isfinite(v)

    out: dict[int, float] = {}
    for prev, step in zip(steps, steps[1:]):
        value = None
        if (prev, step) in acc:
            value = acc[(prev, step)] if ok(acc[(prev, step)]) else None
        else:
            for (s0, e), v in acc.items():
                if e != step:
                    continue
                if s0 == prev:
                    value = v if ok(v) else None
                    break
                base = acc.get((s0, prev)) if prev != s0 else 0.0
                if (s0, prev) in acc or prev == s0:
                    value = (v - base) if ok(v) and ok(base) else None
                    break
        if value is None:
            continue
        if value < -tol:
            if flags is not None:
                flags.append(f"negative accumulation change {value:.4g} at step {step}")
            continue
        out[step] = max(0.0, value)
    return out


def normalise(source: str, raw: dict[tuple[str, int, int], float], acc: dict[int, dict], run: datetime,
              steps: list[int], flags: list | None = None) -> pd.DataFrame:
    """raw[(field, step, point_index)] (native units) -> canonical long table."""
    flags = [] if flags is None else flags
    rows = []
    for i, p in enumerate(POINTS):
        precip = interval_precip(dict(acc.get(i, {})), steps, PACKING_TOL.get(source, 0.05), flags)
        for step in steps:
            g = lambda k: raw.get((k, step, i), math.nan)  # noqa: E731
            valid = run + timedelta(hours=step)
            vals: dict[str, float] = {}
            if not math.isnan(g("t2")):
                vals["temperature_2m"] = g("t2") - 273.15
            if not math.isnan(g("rh2")):
                vals["relative_humidity_2m"] = g("rh2")
            elif not math.isnan(g("td2")) and not math.isnan(g("t2")):
                vals["relative_humidity_2m"] = rh_from_dewpoint(g("t2") - 273.15, g("td2") - 273.15)
            if not math.isnan(g("msl")):
                vals["pressure_msl"] = g("msl") / 100.0
            if not math.isnan(g("sp")):
                vals["surface_pressure"] = g("sp") / 100.0
            if not math.isnan(g("tcc")):
                vals["cloud_cover"] = g("tcc") * (100.0 if source == "ecmwf" else 1.0)
            for h in (10, 100):
                u, v = g(f"u{h}"), g(f"v{h}")
                if not (math.isnan(u) or math.isnan(v)):
                    vals[f"wind_speed_{h}m"], vals[f"wind_direction_{h}m"] = wind(u, v)
            if not math.isnan(g("gust")) and not (source == "ecmwf" and step == 0):
                vals["wind_gusts_10m"] = g("gust")  # IFS 10fg is a max over the previous period: none at step 0
            if step in precip:
                vals["precipitation"] = precip[step] * (1000.0 if source == "ecmwf" else 1.0)  # m -> mm
            for var, value in vals.items():
                lo, hi = RANGES[UNITS_EXT[var]]
                if not lo - 1e-6 <= value <= hi + 1e-6:
                    raise SourceError(f"{source} {p.id} {var} step {step}: {value} outside {lo}..{hi}")
                rows.append((p.id, valid, var, round(value, 3)))
    return pd.DataFrame(rows, columns=["point", "valid_utc", "variable", "value"])


# --- collection -----------------------------------------------------------------------------
@dataclass
class RunResult:
    source: str
    run: datetime
    frame: pd.DataFrame
    published: str  # newest S3 LastModified among the files used
    messages: list[dict] = field(default_factory=list)
    cells: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def _messages(source: str, http: Http, run: datetime, step: int) -> list[Message]:
    if source == "gfs":
        url = gfs_file(run, step)
        idx, _ = http.fetch(url + ".idx")
        head, hdrs = http.fetch(url, (0, 0))
        size = int(hdrs.get("content-range", "/0").split("/")[-1] or 0) or None
        return parse_gfs_idx(idx.decode(), url, step, size)
    idx, _ = http.fetch(ecmwf_file(run, step, "index"))
    return parse_ecmwf_index(idx.decode(), ecmwf_file(run, step, "grib2"), step)


def fetch_run(source: str, run: datetime, http: Http, steps: tuple[int, ...] = STEPS) -> RunResult:
    raw: dict = {}
    acc: dict[int, dict] = {}
    log, cells, published = [], None, None
    for step in steps:
        for m in _messages(source, http, run, step):
            body, hdrs = http.fetch(m.url, (m.offset, m.offset + m.length - 1))
            lm = _http_date(hdrs.get("last-modified", ""))
            if lm is not None and (published is None or lm > published):
                published = lm
            values = decode_points(body)
            if cells is None:
                cells = [dict(point=p.id, grid_latitude=la, grid_longitude=lo) for p, (_v, la, lo) in zip(POINTS, values)]
            for i, (v, _la, _lo) in enumerate(values):
                if m.period:
                    acc.setdefault(i, {})[m.period] = v
                else:
                    raw[(m.key, step, i)] = v
            log.append(dict(field=m.key, step=step, period=list(m.period) if m.period else None, url=m.url,
                            offset=m.offset, length=m.length, sha256=hashlib.sha256(body).hexdigest(),
                            last_modified=lm.isoformat() if lm else None))
    if not log:
        raise SourceError(f"{source}: no messages found for {run:%Y-%m-%d %HZ}")
    flags: list = []
    frame = normalise(source, raw, acc, run, list(steps), flags)
    res = RunResult(source, run, frame, published.isoformat() if published else "", log, cells or [])
    res.flags = flags
    return res


def _http_date(value: str) -> datetime | None:
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(value).astimezone(UTC) if value else None
    except (TypeError, ValueError):
        return None


def latest_complete_run(source: str, http: Http, now: datetime, steps: tuple[int, ...] = STEPS) -> datetime | None:
    """Newest 6-hourly run whose LAST needed step file already exists (fully published)."""
    base = now.replace(minute=0, second=0, microsecond=0)
    base -= timedelta(hours=base.hour % 6)
    for k in range(8):
        run = base - timedelta(hours=6 * k)
        url = gfs_file(run, steps[-1]) + ".idx" if source == "gfs" else ecmwf_file(run, steps[-1], "index")
        try:
            http.fetch(url, (0, 0))
            return run
        except SourceError:
            continue
    return None


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def collect(out: Path, source: str, http: Http, now: datetime, steps: tuple[int, ...] = STEPS,
            clock: Callable[[], datetime] | None = None) -> dict:
    """Store the newest fully published run of ``source`` once; nothing if it is already stored.

    ``retrieved`` (the as-of availability time) is taken from ``clock`` AFTER the last byte was
    downloaded and validated, not at the job start; ``started`` records the attempt start."""
    clock = clock or utcnow
    root = out / ROOT / source
    manifest_path = root / "manifest.json"
    manifest = _load(manifest_path)
    run = latest_complete_run(source, http, now, steps)
    if run is None:
        return {"source": source, "result": "no_complete_run"}
    if any(r["run"] == run.isoformat() for r in manifest.get("runs", [])):
        return {"source": source, "result": "unchanged", "run": run.isoformat()}
    res = fetch_run(source, run, http, steps)
    retrieved = clock()
    root.mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(exist_ok=True)
    csv = res.frame.to_csv(index=False).encode()
    name = f"{run:%Y%m%dT%H%MZ}.csv.gz"
    with gzip.GzipFile(root / "runs" / name, "wb", mtime=0) as fh:
        fh.write(csv)
    evidence = json.dumps(res.messages, indent=0).encode()
    ev_name = f"{run:%Y%m%dT%H%MZ}.messages.json.gz"
    with gzip.GzipFile(root / "runs" / ev_name, "wb", mtime=0) as fh:
        fh.write(evidence)
    entry = dict(run=run.isoformat(), started=now.isoformat(), retrieved=retrieved.isoformat(),
                 published=res.published, file=f"runs/{name}", sha256=hashlib.sha256(csv).hexdigest(),
                 evidence=f"runs/{ev_name}", evidence_sha256=hashlib.sha256(evidence).hexdigest(),
                 steps=list(steps), cells=res.cells, messages=len(res.messages), flags=res.flags,
                 values=int(len(res.frame)), bytes=http.bytes, requests=http.requests)
    runs = [r for r in manifest.get("runs", []) if r["run"] != entry["run"]] + [entry]
    manifest_path.write_text(json.dumps({"source": source, "runs": sorted(runs, key=lambda r: r["run"])}, indent=1) + "\n")
    return {"source": source, "result": "stored", "run": run.isoformat(), "values": entry["values"],
            "flags": len(res.flags),
            "bytes": http.bytes, "requests": http.requests}


def available_runs(out: Path, source: str):
    from forecasting.features import Run

    return [Run(datetime.fromisoformat(r["run"]), datetime.fromisoformat(r["retrieved"]))
            for r in _load(out / ROOT / source / "manifest.json").get("runs", [])]


def load_run(out: Path, source: str, run: datetime) -> pd.DataFrame:
    root = out / ROOT / source
    entry = next(r for r in _load(root / "manifest.json")["runs"] if r["run"] == run.isoformat())
    body = gzip.decompress((root / entry["file"]).read_bytes())
    if hashlib.sha256(body).hexdigest() != entry["sha256"]:
        raise SourceError("stored source table altered")
    df = pd.read_csv(pd.io.common.BytesIO(body))
    df["valid_utc"] = pd.to_datetime(df["valid_utc"], utc=True)
    return df


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)
