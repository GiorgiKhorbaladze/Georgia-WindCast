"""Private forecast archive (owner decision 21.11.2026): no MW forecast value on the public branch,
archive integrity against public commitments, interrupted runs and full recovery. Offline."""

from __future__ import annotations

import gzip
import json
import shutil
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from forecasting import archive, ledger
from forecasting import run as frun
from forecasting.contract import ForecastRecord

T0 = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


def recs(issued, n=4, mw=12.3456):
    return [ForecastRecord("persistence", 1, "gse-only/1", "1h", issued, issued, None,
                           issued + timedelta(hours=k), issued + timedelta(hours=k + 1), mw, None, None, "none", "x" * 64)
            for k in range(n)]


def old_public(tmp_path):
    """A public forecast-data tree as it is today: ledger, backtest, latest.csv, day-ahead rows."""
    pub = tmp_path / "pub"
    ledger.append(pub, recs(T0))
    ledger.append(pub / "backtest", recs(T0 - timedelta(days=1)))
    (pub / "state.json").write_text('{"last_cutoff": "2026-11-20T10:00:00+00:00"}')
    ev = pub / "evaluation"
    ev.mkdir()
    (ev / "latest.csv").write_text("model_id,cadence,issued,cutoff,valid_from,valid_to,mw\npersistence,1h,a,b,c,d,12.3\n")
    (ev / "day_ahead_live.csv").write_text(
        "model_id,model_version,issued,day,forecast_mwh,actual_mwh,complete\np,1,x,2026-11-19,300,280,True\n"
        "p,1,x,2026-11-20,200,260,True\n")
    (ev / "history_live.csv").write_text("day,cadence,horizon_min,model_id,cases,mae,rmse,bias\nd,1h,60,p,4,1,1,0.5\n")
    (ev / "leaderboard.json").write_text(json.dumps({"live": {"leaderboard": [{"mae": 1, "bias": 0.1}]}}))
    (ev / "tournament_gse_only.csv.gz").write_bytes(gzip.compress(b"model_id,pred\np,1\n"))
    w = pub / "weather" / "points"
    w.mkdir(parents=True)
    (w / "manifest.json").write_text("{}")
    return pub


def migrate(tmp_path):
    pub, arc = old_public(tmp_path), tmp_path / "archive"
    arc.mkdir()
    assert archive.seed(arc, pub)["result"] == "seeded"
    shutil.copy2(pub / "evaluation" / "day_ahead_live.csv", arc / "evaluation" / "day_ahead_live.csv")
    archive.publish(arc, pub)
    return pub, arc


def all_public_text(pub):
    out = []
    for p in pub.rglob("*"):
        if p.is_file():
            raw = p.read_bytes()
            out.append(gzip.decompress(raw).decode() if p.suffix == ".gz" else raw.decode("utf-8", "replace"))
    return "\n".join(out)


def test_leak_publish_leaves_no_forecast_value_or_private_file_public(tmp_path):
    pub, arc = migrate(tmp_path)
    assert not (pub / "ledger").exists() and not (pub / "backtest").exists() and not (pub / "state.json").exists()
    for f in ("latest.csv", "day_ahead_live.csv", "tournament_gse_only.csv.gz"):
        assert not (pub / "evaluation" / f).exists()
    text = all_public_text(pub)
    assert "12.3456" not in text and "prediction_mw" not in text and "forecast_mwh" not in text
    hist = pd.read_csv(pub / "evaluation" / "history_live.csv")
    assert "bias" not in hist.columns and hist["mae"].iloc[0] == 1  # per-day bias would reveal the daily mean
    summ = json.loads((pub / "evaluation" / "day_ahead_summary_live.json").read_text())
    assert summ == {"models": [{"model_id": "p", "days": 2, "mae_mwh": 40.0}]}  # no per-day value
    assert (pub / "weather" / "points" / "manifest.json").exists()  # weather inputs stay public
    assert (arc / "evaluation" / "latest.csv").exists() and ledger.read_all(arc)[0].prediction_mw == 12.3456


def test_leak_scan_refuses_any_forbidden_column_or_private_path(tmp_path):
    pub, _ = migrate(tmp_path)
    (pub / "evaluation" / "extra.csv").write_text("model_id,prediction_mw\np,1\n")
    with pytest.raises(archive.LeakError):
        archive.scan(pub)
    (pub / "evaluation" / "extra.csv").unlink()
    (pub / "evaluation" / "latest.csv").write_text("x\n")
    with pytest.raises(archive.LeakError):
        archive.scan(pub)


def test_seed_copies_every_file_byte_for_byte_and_never_overwrites_an_archive(tmp_path):
    pub, arc = old_public(tmp_path), tmp_path / "archive"
    arc.mkdir()
    before = {p.relative_to(pub): archive.sha256(p) for p in archive.ledger_files(pub)}
    assert archive.seed(arc, pub)["files"] >= 6
    assert {p.relative_to(arc): archive.sha256(p) for p in archive.ledger_files(arc)} == before
    assert archive.seed(arc, pub)["result"] == "archive_not_empty"


def test_corruption_or_partial_restore_is_detected(tmp_path):
    pub, arc = migrate(tmp_path)
    assert archive.verify(arc, pub)["result"] == "verified"
    f = archive.ledger_files(arc)[0]
    data = bytearray(f.read_bytes())
    data[20] ^= 0xFF
    f.write_bytes(bytes(data))
    with pytest.raises(archive.IntegrityError, match="changed"):
        archive.verify(arc, pub)
    f.unlink()
    with pytest.raises(archive.IntegrityError, match="missing"):
        archive.verify(arc, pub)


def test_interrupted_run_archive_ahead_of_public_still_verifies(tmp_path):
    """Archive pushed, public push failed: the archive only grew by appended members."""
    pub, arc = migrate(tmp_path)
    ledger.append(arc, recs(T0 + timedelta(minutes=15)))  # same day file, appended after the commitment
    assert archive.verify(arc, pub)["result"] == "verified"
    archive.publish(arc, pub)  # the next run republishes idempotently
    assert archive.verify(arc, pub)["result"] == "verified"


def test_full_recovery_public_projection_is_rebuilt_from_the_archive_alone(tmp_path):
    pub, arc = migrate(tmp_path)
    snapshot = {p.relative_to(pub): p.read_bytes() for p in pub.rglob("*") if p.is_file()}
    fresh = tmp_path / "fresh_pub"
    shutil.copytree(pub / "weather", fresh / "weather")
    archive.publish(arc, fresh)
    rebuilt = {p.relative_to(fresh): p.read_bytes() for p in fresh.rglob("*") if p.is_file()}
    assert rebuilt == snapshot
    clone = tmp_path / "restored_archive"
    shutil.copytree(arc, clone)  # e.g. a fresh clone of the private repository
    assert archive.verify(clone, pub)["result"] == "verified"


def test_cli_commands_and_their_output_carry_no_values(tmp_path, capsys):
    pub, arc = old_public(tmp_path), tmp_path / "archive"
    arc.mkdir()
    for cmd in ("seed", "publish", "verify"):
        assert frun.main([cmd, "--out-dir", str(arc), "--public-dir", str(pub)]) == 0
    out = capsys.readouterr().out
    assert "12.3456" not in out and "prediction" not in out


def test_workflows_never_write_values_to_the_public_branch_and_stop_without_the_archive():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / ".github/workflows"
    for name in ("forecast.yml", "forecast-tournament.yml"):
        wf = (root / name).read_text(encoding="utf-8")
        assert "secrets.FORECAST_ARCHIVE_SSH_KEY" in wf and "vars.FORECAST_ARCHIVE_REPO" in wf
        assert "nothing issued" in wf and "StrictHostKeyChecking=yes" in wf
        assert "--out-dir ../../archive" in wf and "publish --out-dir ../../archive --public-dir ../../pub" in wf
        assert wf.index("Push the private archive first") < wf.index("Public projection") < wf.index(
            "Push the public projection")
        assert "--out-dir ../../out" not in wf
    import mwmodel
    assert mwmodel.PUBLISH_FORECAST is False
