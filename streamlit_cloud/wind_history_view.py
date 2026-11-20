"""Data and calculations for the "Wind Generation History" page (Issue #52). No Streamlit here.

Input: public monthly records (``wind_history.public_records``). Everything is computed from
monthly station values; missing months stay missing (NaN), never zero; nothing is interpolated.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from html import escape  # XML-safe for text and attributes (&, <, >, quotes); no XML parser

import httpx
import pandas as pd

import wind_history as wh

HERE = Path(__file__).resolve().parent
SEED = HERE / "history_seed" / "wind_monthly.csv"
REMOTE = "history/wind_monthly.csv"


def remote_csv(base_url: str, timeout: float = 10.0) -> str | None:
    """The monitored archive on the data branch; ``None`` before the first monitor run."""
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        resp = client.get(base_url.rstrip("/") + "/" + REMOTE)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.text


@dataclass(frozen=True)
class Loaded:
    records: list[wh.MonthRecord]
    origin: str  # "archive" (data branch) | "seed" (reviewed owner import bundled with the app)
    error: str | None = None


def load(base_url: str) -> Loaded:
    error = None
    try:
        text = remote_csv(base_url)
        if text is not None:
            return Loaded(wh.public_records(wh.parse_records(text)), "archive")
    except (httpx.HTTPError, wh.HistoryFormatError) as exc:
        error = type(exc).__name__  # fall back to the reviewed seed, and say so
    return Loaded(wh.public_records(wh.parse_records(SEED.read_text(encoding="utf-8"))), "seed", error)


def frame(records: list[wh.MonthRecord]) -> pd.DataFrame:
    rows = [dict(station_id=r.station_id, year=r.year, month=r.month, gwh=r.energy,
                 status=r.verification_status, official=r.verification_status in wh.OFFICIAL_STATES,
                 conflict=r.verification_status == wh.CONFLICT, source_kind=r.source_kind,
                 source_url=r.source_url, source_document_id=r.source_document_id,
                 source_sha256=r.source_sha256, revision_id=r.revision_id, last_modified=r.last_modified)
            for r in records]
    cols = ["station_id", "year", "month", "gwh", "status", "official", "conflict", "source_kind", "source_url",
            "source_document_id", "source_sha256", "revision_id", "last_modified"]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    df["period"] = df["year"] * 12 + df["month"] - 1
    return df.sort_values(["period", "station_id"]).reset_index(drop=True)


def stations_in(df: pd.DataFrame) -> list[str]:
    order = [s.id for s in wh.STATIONS]
    return sorted(set(df["station_id"]), key=order.index)


def ym(period: int) -> tuple[int, int]:
    return period // 12, period % 12 + 1


# --- coverage ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Coverage:
    station_id: str
    first: tuple[int, int]
    last: tuple[int, int]
    months: int
    gaps: list[tuple[int, int]]  # months inside first..last without a value
    official: int


def coverage(df: pd.DataFrame) -> list[Coverage]:
    out = []
    for sid in stations_in(df):
        s = df[df.station_id == sid]
        lo, hi = int(s.period.min()), int(s.period.max())
        have = set(s.period)
        out.append(Coverage(sid, ym(lo), ym(hi), len(s), [ym(p) for p in range(lo, hi + 1) if p not in have],
                            int(s.official.sum())))
    return out


def latest_period(df: pd.DataFrame) -> int | None:
    return None if df.empty else int(df.period.max())


def fleet_month_missing(df: pd.DataFrame, period: int) -> list[str]:
    """Stations already reporting before ``period`` that have no value for it."""
    started = df[df.period < period].station_id.unique()
    have = set(df[df.period == period].station_id)
    return [s for s in stations_in(df) if s in started and s not in have]


# --- annual --------------------------------------------------------------------------------
def year_complete(df: pd.DataFrame, year: int) -> bool:
    """Calendar-complete: every month has data and no reporting station skipped a month."""
    y = df[df.year == year]
    if set(y.month) != set(range(1, 13)):
        return False
    return not any(fleet_month_missing(df, year * 12 + m - 1) for m in range(1, 13))


def annual(df: pd.DataFrame) -> pd.DataFrame:
    """Rows: year, station_id, gwh, months, complete (fleet calendar completeness)."""
    if df.empty:
        return pd.DataFrame(columns=["year", "station_id", "gwh", "months", "complete"])
    g = df.groupby(["year", "station_id"]).agg(gwh=("gwh", "sum"), months=("month", "count")).reset_index()
    complete = {y: year_complete(df, y) for y in g.year.unique()}
    g["complete"] = g.year.map(complete)
    g["gwh"] = g.gwh.round(6)
    return g


def latest_complete_year(df: pd.DataFrame) -> int | None:
    years = sorted(set(df.year), reverse=True) if not df.empty else []
    return next((y for y in years if year_complete(df, y)), None)


# --- year to date and comparable year-on-year ----------------------------------------------
@dataclass(frozen=True)
class YoY:
    year: int
    months: list[int]
    current: float
    previous: float | None
    change_pct: float | None
    existing: list[str]  # stations with every compared month in both years
    existing_current: float
    existing_previous: float | None
    existing_pct: float | None
    new_farms: list[str]
    new_contribution: float
    missing_previous: list[tuple[str, int]]  # (station, month) present now, absent a year earlier


def ytd_yoy(df: pd.DataFrame, year: int, through_month: int) -> YoY:
    months = list(range(1, through_month + 1))
    cur = df[(df.year == year) & df.month.isin(months)]
    prev = df[(df.year == year - 1) & df.month.isin(months)]
    stations = stations_in(cur) if not cur.empty else []
    existing = [s for s in stations
                if set(cur[cur.station_id == s].month) == set(months) == set(prev[prev.station_id == s].month)]
    new = [s for s in stations if prev[prev.station_id == s].empty and df[(df.station_id == s) & (df.year < year)].empty]
    current = float(cur.gwh.sum())
    previous = float(prev.gwh.sum()) if set(prev.month) == set(months) else None
    ex_cur = float(cur[cur.station_id.isin(existing)].gwh.sum())
    ex_prev = float(prev[prev.station_id.isin(existing)].gwh.sum()) if existing else None
    missing_prev = [(s, m) for s in stations if s not in new for m in months
                    if not cur[(cur.station_id == s) & (cur.month == m)].empty
                    and prev[(prev.station_id == s) & (prev.month == m)].empty]
    return YoY(
        year, months, current, previous,
        None if not previous else (current / previous - 1) * 100,
        existing, ex_cur, ex_prev, None if not ex_prev else (ex_cur / ex_prev - 1) * 100,
        new, float(cur[cur.station_id.isin(new)].gwh.sum()), missing_prev,
    )


def monthly_yoy(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Per month: change vs the same month a year earlier, split into existing farms and new farms."""
    rows = []
    first_year = df.groupby("station_id").year.min().to_dict()
    for m in range(1, 13):
        cur = df[(df.year == year) & (df.month == m)]
        prev = df[(df.year == year - 1) & (df.month == m)]
        if cur.empty:
            rows.append(dict(month=m, current=None, previous=None, existing_delta=None, new_farms=None))
            continue
        both = sorted(set(cur.station_id) & set(prev.station_id))
        new = [s for s in cur.station_id if first_year[s] == year]
        rows.append(dict(
            month=m, current=float(cur.gwh.sum()), previous=float(prev.gwh.sum()) if not prev.empty else None,
            existing_delta=float(cur[cur.station_id.isin(both)].gwh.sum() - prev[prev.station_id.isin(both)].gwh.sum())
            if both else None,
            new_farms=float(cur[cur.station_id.isin(new)].gwh.sum()) if new else 0.0,
        ))
    return pd.DataFrame(rows)


# --- monthly, heatmap and cumulative -------------------------------------------------------
def month_matrix(df: pd.DataFrame, stations: list[str] | None = None) -> pd.DataFrame:
    """Year x month fleet (or selected stations) totals; NaN where no station reported."""
    d = df if stations is None else df[df.station_id.isin(stations)]
    if d.empty:
        return pd.DataFrame()
    m = d.pivot_table(index="year", columns="month", values="gwh", aggfunc="sum")
    return m.reindex(columns=range(1, 13))


def cumulative(df: pd.DataFrame, year: int, stations: list[str] | None = None) -> list[float | None]:
    """Running total from the year's first reported month; stops (None) at the first later month
    without data and never bridges a gap. Months before the first report stay empty."""
    row = month_matrix(df, stations)
    out: list[float | None] = []
    total, started, broken = 0.0, False, False
    for m in range(1, 13):
        value = row.loc[year, m] if year in row.index else float("nan")
        if broken or pd.isna(value):
            broken = started
            out.append(None)
        else:
            started = True
            total += float(value)
            out.append(round(total, 6))
    return out


# --- exports -------------------------------------------------------------------------------
EXPORT_COLUMNS = ["station_id", "name_ka", "name_en", "year", "month", "gwh", "status", "source_kind",
                  "source_document_id", "source_url", "source_sha256", "revision_id", "last_modified"]


def export_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["name_ka"] = out.station_id.map(lambda s: wh.STATION_BY_ID[s].name_ka)
    out["name_en"] = out.station_id.map(lambda s: wh.STATION_BY_ID[s].name_en)
    return out[EXPORT_COLUMNS]


def to_csv(df: pd.DataFrame) -> bytes:
    return export_frame(df).to_csv(index=False).encode("utf-8-sig")  # BOM: Excel opens Georgian text


def _col(i: int) -> str:
    name = ""
    while True:
        i, r = divmod(i, 26)
        name = chr(65 + r) + name
        if i == 0:
            return name
        i -= 1


def to_xlsx(df: pd.DataFrame, sheet: str = "wind_monthly") -> bytes:
    """Minimal single-sheet .xlsx (inline strings, numeric cells) using only the stdlib."""
    data = export_frame(df)
    rows = [list(data.columns)] + data.astype(object).where(data.notna(), None).values.tolist()
    xml_rows = []
    for r, values in enumerate(rows, 1):
        cells = []
        for c, value in enumerate(values):
            ref = f"{_col(c)}{r}"
            if value is None:
                continue
            if isinstance(value, bool):
                value = str(value)
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value!r}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>"),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>'),
        "xl/workbook.xml": (
            f'<?xml version="1.0" encoding="UTF-8"?><workbook {ns} xmlns:r="{rel}"><sheets>'
            f'<sheet name="{escape(sheet)}" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'),
        "xl/worksheets/sheet1.xml": (
            f'<?xml version="1.0" encoding="UTF-8"?><worksheet {ns}><sheetData>{"".join(xml_rows)}</sheetData></worksheet>'),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()
