"""Publication gate for website MW forecasts (owner decision pending; display switch stays off).

Evidence comes ONLY from the live ledger: forecasts as issued in real time, scored after the fact
(``leaderboard.json`` -> ``live``). The rolling-origin backtest is retrospective and never counts
towards the gate, because it can be re-run with hindsight about model choices.

A (model, cadence, horizon) passes when ALL hold:

* at least ``MIN_DAYS`` independent local days and ``MIN_CASES`` complete cases. 28 days spans four
  weekly cycles and several synoptic regimes; 14 days is too short for wind (one or two weather
  regimes can dominate);
* positive skill against persistence with the 90 % day-block bootstrap interval entirely above 0;
* bias small relative to error: ``|bias| <= MAX_BIAS_SHARE * MAE``, so a systematic offset does not
  dominate;
* the live record is operationally complete: at most ``MAX_LATE_SHARE`` of forecasts issued after
  their valid start, and at least ``MIN_COMPLETE_SHARE`` of matured forecasts scoreable.

Persistence is the reference and is never "passed": showing it as a forecast adds nothing.
Thresholds are explicit constants so the owner can change them knowingly.
"""

from __future__ import annotations

MIN_DAYS = 28
MIN_CASES = 500
MAX_BIAS_SHARE = 0.3
MAX_LATE_SHARE = 0.10
MIN_COMPLETE_SHARE = 0.90
REFERENCE = "persistence"


def evaluate(board: dict | None) -> dict:
    """Per row of the live leaderboard: pass/fail with the reasons; plus the operational check."""
    live = (board or {}).get("live") or {}
    cov = live.get("coverage") or {}
    matured = cov.get("matured") or 0
    complete_share = (cov.get("complete", 0) / matured) if matured else 0.0
    late = cov.get("late_share", 1.0)
    ops = []
    if late > MAX_LATE_SHARE:
        ops.append(f"late share {late:.0%} > {MAX_LATE_SHARE:.0%}")
    if complete_share < MIN_COMPLETE_SHARE:
        ops.append(f"complete share {complete_share:.0%} < {MIN_COMPLETE_SHARE:.0%}")
    rows = []
    for r in live.get("leaderboard") or []:
        if r.get("model_id") == REFERENCE:
            continue
        why = list(ops)
        if (r.get("days") or 0) < MIN_DAYS:
            why.append(f"{r.get('days', 0)} independent days < {MIN_DAYS}")
        if (r.get("cases") or 0) < MIN_CASES:
            why.append(f"{r.get('cases', 0)} cases < {MIN_CASES}")
        ci = r.get("skill_90ci")
        if not ci or ci[0] is None or ci[0] <= 0:
            why.append("skill 90% interval not above 0")
        mae, bias = r.get("mae"), r.get("bias")
        if mae is None or bias is None or abs(bias) > MAX_BIAS_SHARE * mae:
            why.append("bias too large relative to MAE")
        rows.append({"model_id": r["model_id"], "cadence": r.get("cadence"), "horizon_min": r.get("horizon_min"),
                     "passes": not why, "reasons": why})
    return {"source": "live (as-issued, out-of-sample)", "rows": rows,
            "passing": [x for x in rows if x["passes"]],
            "criteria": {"min_days": MIN_DAYS, "min_cases": MIN_CASES, "max_bias_share": MAX_BIAS_SHARE,
                         "max_late_share": MAX_LATE_SHARE, "min_complete_share": MIN_COMPLETE_SHARE}}


def passes(gate: dict, model_id: str, cadence: str, horizon_min: int) -> bool:
    return any(x["model_id"] == model_id and x["cadence"] == cadence and x["horizon_min"] == horizon_min
               for x in gate.get("passing", []))
