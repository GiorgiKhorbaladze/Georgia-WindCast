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

``python -m forecasting.run tournament --data-dir DATA --out-dir OUT``
    Daily challenger tournament (forecasting/tournament.py): all available models on the same
    independent day folds, GSE-only and, once as-of weather runs exist, with weather ablations.

``python -m forecasting.run evaluate --data-dir DATA --out-dir OUT``
    Scores both ledgers against the GSE observations and writes OUT/evaluation/*.

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


def cmd_tournament(data_dir: Path, out: Path, now: datetime) -> dict:
    from forecasting import tournament, weather_points

    obs = load_obs(data_dir, now.date(), EVAL_DAYS)
    report: dict = {"generated_at": now.isoformat(), "independence_unit": "local day",
                    "min_days": tournament.MIN_DAYS, "horizons_h": list(tournament.HORIZONS), "variants": {}}
    runs = weather_points.available_runs(out)
    variants = {"gse_only": None}
    if runs:
        for name, regions in (("local_weather", ("east",)), ("local_plus_west", ("east", "central", "west"))):
            variants[name] = tournament.weather_features(runs, lambda r: weather_points.load_run(out, r), regions)
    (out / "evaluation").mkdir(parents=True, exist_ok=True)
    for name, fn in variants.items():
        res = tournament.run(obs, weather=fn)
        report["variants"][name] = {"status": res["status"], "scores": res["scores"]}
        res["predictions"].to_csv(out / "evaluation" / f"tournament_{name}.csv.gz", index=False)
    if not runs:
        report["weather_ablation"] = "not run: no as-of weather runs stored yet"
    (out / "evaluation" / "tournament.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
    return {"result": "tournament", "variants": list(variants), "weather_runs": len(runs)}


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
    ap.add_argument("cmd", choices=["issue", "backtest", "evaluate", "weather", "tournament"])
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--force", action="store_true", help="evaluate even if the last run is recent")
    a = ap.parse_args(argv)
    now = datetime.now(UTC).replace(microsecond=0)
    if a.cmd == "tournament":
        result = cmd_tournament(a.data_dir, a.out_dir, now)
    elif a.cmd == "weather":
        result = cmd_weather(a.data_dir, a.out_dir, now)
    elif a.cmd == "evaluate":
        result = cmd_evaluate(a.data_dir, a.out_dir, now, a.force)
    else:
        result = {"issue": cmd_issue, "backtest": cmd_backtest}[a.cmd](a.data_dir, a.out_dir, now)
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
