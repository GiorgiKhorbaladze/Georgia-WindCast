"""Forecast issuing and evaluation CLI (GitHub Actions; Streamlit only reads the outputs).

``python -m forecasting.run issue --data-dir DATA --out-dir OUT``
    Issues every stage-I baseline from the newest GSE observation in DATA (a ``data`` branch
    checkout) and appends to OUT/ledger (``forecast-data`` branch). Nothing is issued twice for
    the same cutoff; nothing is issued for an older cutoff after the fact.

``python -m forecasting.run backtest --data-dir DATA --out-dir OUT``
    Rolling-origin replay over the stored history into OUT/backtest (simulated issue time =
    cutoff, labelled as such). Models see only observations up to each cutoff.

``python -m forecasting.run weather --data-dir DATA --out-dir OUT``
    One batched multi-point weather request, only when the collector saw a new ICON run.

``python -m forecasting.run sources --data-dir DATA --out-dir OUT``
    Independent NWP sources (GFS, ECMWF IFS from AWS Open Data): store each newly published run
    once, at the seven forecasting points (forecasting/weather_sources.py).
``python -m forecasting.run tournament --data-dir DATA --out-dir OUT``
    Daily challenger tournament (forecasting/tournament.py): all available models on the same
    independent day folds, GSE-only and, once as-of weather runs exist, with weather ablations.

``python -m forecasting.run evaluate --data-dir DATA --out-dir OUT``
    Scores both ledgers against the GSE observations and writes OUT/evaluation/*.

``python -m forecasting.run seed|publish|verify --out-dir ARCHIVE --public-dir PUBLIC``
    Private archive (forecasting/archive.py): OUT is the private archive checkout that holds every
    MW forecast; PUBLIC is the public ``forecast-data`` checkout, which receives only aggregated
    scores and hash commitments, never a forecast value.

No publication switch is touched here: ``mwmodel.PUBLISH_FORECAST`` stays False.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE.parent / "backend")]

from forecasting import capacity, evaluate, ledger  # noqa: E402
from forecasting.actuals import series  # noqa: E402
from forecasting.contract import CONTRACT_VERSION, HORIZON_STEPS, ForecastRecord  # noqa: E402
from forecasting.models import BASELINES, CANDIDATES  # noqa: E402
from store import day_path, parse_day_csv  # noqa: E402

LOOKBACK_DAYS = 35


def load_obs(data_dir: Path, until: date, days: int = LOOKBACK_DAYS) -> pd.Series:
    recs = []
    for k in range(days + 1):
        p = data_dir / day_path(until - timedelta(days=k))
        if p.exists():
            recs.extend(parse_day_csv(p.read_text(encoding="utf-8")))
    return series(recs)


def _hash(obs: pd.Series) -> str:
    h = hashlib.sha256()
    for t, v in obs.items():
        h.update(f"{t.isoformat()}={v!r};".encode())
    return h.hexdigest()


def issue_at(obs: pd.Series, cutoff: datetime, issued: datetime) -> list[ForecastRecord]:
    """All baselines x cadences x horizons from observations labelled <= cutoff."""
    seen = obs[obs.index <= cutoff]
    if seen.empty:
        return []
    digest = _hash(seen[seen.index > cutoff - timedelta(days=28)])
    out = []
    for model in BASELINES:
        if not model.ready(seen):
            continue
        for cadence in model.cadences:
            for p in model.predict(seen, cutoff, cadence, HORIZON_STEPS[cadence]):
                out.append(ForecastRecord(model.model_id, model.version, model.feature_version, cadence, issued,
                                          cutoff, None, p.valid_from, p.valid_to, round(p.mw, 4), p.q10, p.q90,
                                          "none", digest))
    return out


def cmd_issue(data_dir: Path, out: Path, now: datetime) -> dict:
    obs = load_obs(data_dir, now.date())
    state_path = out / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if obs.empty:
        return {"result": "no_observations"}
    cutoff = obs.index[-1].to_pydatetime()
    if state.get("last_cutoff") and datetime.fromisoformat(state["last_cutoff"]) >= cutoff:
        return {"result": "no_new_observation", "cutoff": cutoff.isoformat()}
    recs = issue_at(obs, cutoff, now)
    added = ledger.append(out, recs)
    state.update(last_cutoff=cutoff.isoformat(), last_issued_at=now.isoformat(), contract=CONTRACT_VERSION)
    state_path.write_text(json.dumps(state, indent=2) + "\n")
    return {"result": "issued", "cutoff": cutoff.isoformat(), "issued_at": now.isoformat(), "records": added}


def cmd_backtest(data_dir: Path, out: Path, now: datetime, every: timedelta = timedelta(hours=1)) -> dict:
    """Simulated issues at every full hour cutoff (and its 15-minute steps for nowcasts)."""
    obs = load_obs(data_dir, now.date())
    root = out / "backtest"
    done = {r.data_cutoff_utc for r in ledger.read_all(root)} if (root / "ledger").exists() else set()
    added = 0
    cutoffs = [t.to_pydatetime() for t in obs.index if t.minute % 15 == 0]
    for c in cutoffs:
        if c in done or c > obs.index[-1] - timedelta(hours=1):
            continue
        added += ledger.append(root, issue_at(obs, c, c))
    return {"result": "backtest", "records": added, "cutoffs": len(cutoffs)}


EVAL_EVERY = timedelta(minutes=55)
EVAL_DAYS = 400  # score every archived case that still has observations


def cmd_evaluate(data_dir: Path, out: Path, now: datetime, force: bool = False) -> dict:
    board = out / "evaluation" / "leaderboard.json"
    if not force and board.exists():
        last = datetime.fromisoformat(json.loads(board.read_text())["generated_at"])
        if now - last < EVAL_EVERY:
            return {"result": "evaluation_not_due", "last": last.isoformat()}
    obs = load_obs(data_dir, now.date(), EVAL_DAYS)
    constraints = evaluate.parse_constraints((out / "constraints.csv").read_text()
                                             if (out / "constraints.csv").exists() else None)
    report = {"generated_at": now.isoformat(), "contract": CONTRACT_VERSION, "candidates": CANDIDATES,
              "min_days": evaluate.MIN_DAYS, "min_cases": evaluate.MIN_CASES,
              "capacity_factor_enabled": capacity.capacity_factor_enabled(now.date()),
              "capacity_registry": capacity.REGISTRY_VERSION,
              "latest_observation": obs.index[-1].isoformat() if len(obs) else None}
    (out / "evaluation").mkdir(parents=True, exist_ok=True)
    for name, root in (("live", out), ("backtest", out / "backtest")):
        recs = ledger.read_all(root) if (root / "ledger").exists() else []
        df = evaluate.scored_frame(recs, obs, constraints)
        report[name] = dict(coverage=evaluate.coverage(df), leaderboard=evaluate.leaderboard(df),
                            leaderboard_excluding_confirmed_constraints=evaluate.leaderboard(df, True)
                            if constraints else None)
        evaluate.daily_history(df).to_csv(out / "evaluation" / f"history_{name}.csv", index=False)
        evaluate.day_ahead_energy(recs, obs).to_csv(out / "evaluation" / f"day_ahead_{name}.csv", index=False)
        if name == "live" and len(recs):
            latest = max(r.issued_at_utc for r in recs)
            cur = [r for r in recs if r.issued_at_utc == latest]
            pd.DataFrame([dict(model_id=r.model_id, cadence=r.cadence, issued=r.issued_at_utc.isoformat(),
                               cutoff=r.data_cutoff_utc.isoformat(), valid_from=r.valid_from_utc.isoformat(),
                               valid_to=r.valid_to_utc.isoformat(), mw=r.prediction_mw) for r in cur]
                         ).to_csv(out / "evaluation" / "latest.csv", index=False)
    (out / "evaluation" / "leaderboard.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
    return {"result": "evaluated", "live_cases": report["live"]["coverage"], "backtest": report["backtest"]["coverage"]}


def cmd_sources(out: Path, now: datetime) -> dict:
    """Each source independently: a failure of one never blocks the other."""
    import httpx

    from forecasting import weather_sources as ws

    results = []
    with httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=False) as client:
        def get(url: str, headers: dict) -> tuple[int, bytes, dict]:
            r = client.get(url, headers=headers)
            return r.status_code, r.content, {k.lower(): v for k, v in r.headers.items()}
        for source in ("gfs", "ecmwf"):
            try:
                results.append(ws.collect(out, source, ws.Http(get), datetime.now(UTC).replace(microsecond=0),
                                          clock=lambda: datetime.now(UTC).replace(microsecond=0)))
            except Exception as exc:  # reported, never fatal for the other source
                results.append({"source": source, "result": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]})
        import os

        from forecasting import visualcrossing as vc

        try:  # the key comes from the environment only and is never printed or stored
            results.append(vc.collect(out, os.environ.get("VISUAL_CROSSING_API_KEY"),
                                      lambda u: (lambda r: (r.status_code, r.content))(client.get(u)), now))
        except Exception as exc:
            results.append({"source": "visualcrossing", "result": "failed", "error": type(exc).__name__})
    return {"result": "sources", "sources": results, "health": source_health(out, results, now)}


SOURCE_STALE_HOURS = 18  # 4 runs a day per source plus 4-8 h publication lag: 18 h means >= 2 missed runs
STALE_HOURS_BY_SOURCE = {"visualcrossing": 30}  # pilot: one request set a day


def source_health(out: Path, results: list[dict], now: datetime) -> dict:
    """Per-source health, kept in weather/sources/health.json. One failing source never stops the
    others, but the job must not stay green when every source failed in this attempt or when a
    source has stored no new run for SOURCE_STALE_HOURS: then ``alert`` lists why and main() exits 2."""
    from forecasting import weather_sources as ws

    path = out / ws.ROOT / "health.json"
    try:
        prev = json.loads(path.read_text())
    except (OSError, ValueError):
        prev = {}
    sources, alert = {}, []
    for r in results:
        src = r["source"]
        h = dict(prev.get("sources", {}).get(src, {}))
        failed = r.get("result") == "failed"
        h["last_attempt"], h["last_result"] = now.isoformat(), r.get("result")
        h["consecutive_failures"] = h.get("consecutive_failures", 0) + 1 if failed else 0
        if failed:
            h["last_error"] = r.get("error")
        else:
            h["last_success"] = now.isoformat()
        runs = [x["run"] for x in ws._load(out / ws.ROOT / src / "manifest.json").get("runs", [])]
        h["newest_run"] = max(runs) if runs else None
        age = (now - datetime.fromisoformat(h["newest_run"])).total_seconds() / 3600 if runs else None
        h["newest_run_age_h"] = None if age is None else round(age, 1)
        limit = STALE_HOURS_BY_SOURCE.get(src, SOURCE_STALE_HOURS)
        h["stale"] = age is None or age > limit
        if r.get("result") == "no_key":
            h["stale"] = False  # pilot not configured: reported in the result, not an outage
        if h["stale"]:
            alert.append(f"{src}: no stored run newer than {limit} h")
        sources[src] = h
    configured = [r for r in results if r.get("result") != "no_key"]  # an unconfigured pilot is not a source
    if configured and all(r.get("result") == "failed" for r in configured):
        alert.insert(0, "every source failed in this attempt")
    report = {"checked_at": now.isoformat(), "stale_after_h": SOURCE_STALE_HOURS, "sources": sources, "alert": alert}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1) + "\n")
    return report
def cmd_tournament(data_dir: Path, out: Path, now: datetime, weather_dir: Path | None = None) -> dict:
    """GSE-only, then for every weather source with stored runs: local and local + west predictors.

    Sources: Open-Meteo ICON (forecasting/weather_points.py), NOAA GFS and ECMWF IFS
    (forecasting/weather_sources.py). Every variant uses the same folds, so source x predictor-set
    x model combinations are compared on identical independent days."""
    from forecasting import tournament, weather_points, weather_sources

    wdir = weather_dir or out  # weather inputs live on the public branch; predictions go to the archive

    obs = load_obs(data_dir, now.date(), EVAL_DAYS)
    report: dict = {"generated_at": now.isoformat(), "independence_unit": "local day",
                    "min_days": tournament.MIN_DAYS, "horizons_h": list(tournament.HORIZONS), "variants": {},
                    "sources": {}}
    loaders = {"icon_openmeteo": (weather_points.available_runs(wdir), lambda r: weather_points.load_run(wdir, r))}
    for src in ("gfs", "ecmwf", "visualcrossing"):
        loaders[src] = (weather_sources.available_runs(wdir, src),
                        lambda r, s=src: weather_sources.load_run(wdir, s, r))
    variants = {"gse_only": None}
    for src, (runs, load) in loaders.items():
        report["sources"][src] = {"runs": len(runs)}
        if runs:
            for name, regions in (("local_weather", ("east",)), ("local_plus_west", ("east", "central", "west"))):
                variants[f"{src}_{name}"] = tournament.weather_features(runs, load, regions)
    (out / "evaluation").mkdir(parents=True, exist_ok=True)
    for name, fn in variants.items():
        res = tournament.run(obs, weather=fn)
        report["variants"][name] = {"status": res["status"], "scores": res["scores"]}
        res["predictions"].to_csv(out / "evaluation" / f"tournament_{name}.csv.gz", index=False)
    if len(variants) == 1:
        report["weather_ablation"] = "not run: no as-of weather runs stored yet"
    (out / "evaluation" / "tournament.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
    return {"result": "tournament", "variants": list(variants), "sources": report["sources"]}


def cmd_weather(data_dir: Path, out: Path, now: datetime) -> dict:
    import os

    import httpx

    from forecasting import weather_points

    headers = {"Accept": "application/json"}
    if ua := os.environ.get("WINDCAST_USER_AGENT"):
        headers["User-Agent"] = ua
    with httpx.Client(timeout=httpx.Timeout(30.0), headers=headers, follow_redirects=False) as client:
        def fetch(u: str) -> weather_points.Response:
            r = client.get(u)
            return weather_points.Response(r.status_code, r.content)
        return weather_points.collect(out, data_dir, fetch, now)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["issue", "backtest", "evaluate", "weather", "sources", "tournament",
                                    "seed", "publish", "verify", "check-private"])
    ap.add_argument("--data-dir", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--public-dir", type=Path, help="public forecast-data checkout (archive commands, weather)")
    ap.add_argument("--force", action="store_true", help="evaluate even if the last run is recent")
    a = ap.parse_args(argv)
    now = datetime.now(UTC).replace(microsecond=0)
    if a.cmd == "check-private":
        import os

        from forecasting import archive

        print(json.dumps(archive.check_private(os.environ["ARCHIVE_REPO"], os.environ["GITHUB_REPOSITORY"],
                                               os.environ.get("ARCHIVE_METADATA_TOKEN"))))
        return 0
    if a.cmd in ("seed", "publish", "verify"):
        from forecasting import archive

        if a.public_dir is None:
            ap.error("--public-dir is required")
        result = getattr(archive, a.cmd)(a.out_dir, a.public_dir)
        print(json.dumps(result, default=str))
        return 0
    if a.cmd == "sources":
        result = cmd_sources(a.out_dir, now)
    elif a.data_dir is None:
        ap.error("--data-dir is required")
    elif a.cmd == "tournament":
        result = cmd_tournament(a.data_dir, a.out_dir, now, a.public_dir)
    elif a.cmd == "weather":
        result = cmd_weather(a.data_dir, a.out_dir, now)
    elif a.cmd == "evaluate":
        result = cmd_evaluate(a.data_dir, a.out_dir, now, a.force)
    else:
        result = {"issue": cmd_issue, "backtest": cmd_backtest}[a.cmd](a.data_dir, a.out_dir, now)
    print(json.dumps(result, default=str))
    if a.cmd == "sources" and result["health"]["alert"]:
        print("ALERT: " + "; ".join(result["health"]["alert"]), file=sys.stderr)
        return 2  # partial results are still committed by the workflow; the run is then marked failed
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
