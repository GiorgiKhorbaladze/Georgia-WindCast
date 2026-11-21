"""Offline migration rehearsal (PR #69 security review): the full migration against REAL git
remotes (local bare repositories), with synthetic data and NO credentials. It replaces the
credentialed PR rehearsal, which would have run PR-controlled code next to the archive secrets.

Per run, as forecast.yml / forecast-tournament.yml do: clone public + archive, seed, verify,
write, push the archive FIRST, publish (covered + scan), push public.

Two kinds of interruption are covered and must not be conflated:
* "stopped before push" (fail_at=...): the run ends before a push is attempted;
* REAL `git push` failures injected into the remote: a pre-receive hook that rejects, a
  concurrent update that makes the push non-fast-forward, and a remote that disappears
  (transport loss). In production the push step retries 4 times and then fails the job, so the
  public step never runs; here a failed push raises and the run stops the same way.
These are local bare repositories, not the private GitHub archive; authentication and GitHub's
own behaviour are outside this test."""

from __future__ import annotations

import shutil
import subprocess
from datetime import timedelta

import pytest

from forecasting import archive, ledger
from test_archive import T0, old_public, recs


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def remotes(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    pub_bare, arc_bare = tmp_path / "pub.git", tmp_path / "archive.git"
    git(tmp_path, "init", "-q", "--bare", str(pub_bare))
    git(tmp_path, "init", "-q", "--bare", str(arc_bare))
    seed_dir = old_public(tmp_path / "seedsrc")  # the public branch as it is before the migration
    git(seed_dir, "init", "-q", "-b", "forecast-data")
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        git(seed_dir, "config", k, v)
    git(seed_dir, "add", "-A")
    git(seed_dir, "commit", "-q", "-m", "pre-migration")
    git(seed_dir, "push", "-q", str(pub_bare), "forecast-data")
    return tmp_path, pub_bare, arc_bare, git(seed_dir, "rev-parse", "HEAD")


def checkout(tmp, bare, branch, name):
    d = tmp / name
    if d.exists():
        shutil.rmtree(d)
    git(tmp, "init", "-q", str(d))
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        git(d, "config", k, v)
    git(d, "remote", "add", "origin", str(bare))
    heads = git(d, "ls-remote", "--heads", "origin", branch)
    if heads:
        git(d, "fetch", "-q", "origin", branch)
        git(d, "checkout", "-q", "-b", branch, "FETCH_HEAD")
    else:
        git(d, "checkout", "-q", "--orphan", branch)
    return d


def commit_push(d, branch, msg, push=True):
    git(d, "add", "-A")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=d).returncode == 0:
        return
    git(d, "commit", "-q", "-m", msg)
    if push:
        git(d, "push", "-q", "origin", branch)


def run(tmp, pub_bare, arc_bare, write, fail_at=None):
    pub = checkout(tmp, pub_bare, "forecast-data", "pub")
    arc = checkout(tmp, arc_bare, "main", "arc")
    archive.seed(arc, pub)
    archive.verify(arc, pub)
    write(arc)
    commit_push(arc, "main", "archive", push=fail_at != "archive_push")
    if fail_at == "archive_push":
        return
    archive.publish(arc, pub)
    commit_push(pub, "forecast-data", "public", push=fail_at != "public_push")


def forecast(k):
    return lambda arc: ledger.append(arc, recs(T0 + timedelta(minutes=15 * k)))


def test_full_migration_against_real_git_remotes(remotes):
    tmp, pub_bare, arc_bare, pre = remotes
    rows0 = len(ledger.read_all(tmp / "seedsrc" / "pub"))  # live ledger before the migration
    run(tmp, pub_bare, arc_bare, forecast(1), fail_at="archive_push")   # 1: archive push fails
    run(tmp, pub_bare, arc_bare, forecast(2), fail_at="public_push")    # 2: public push fails
    run(tmp, pub_bare, arc_bare, lambda arc: None)                       # 3: tournament-like, completes
    run(tmp, pub_bare, arc_bare, forecast(3))                            # 4: normal
    # fresh clones of both remotes = full recovery
    pub = checkout(tmp, pub_bare, "forecast-data", "pub_fresh")
    arc = checkout(tmp, arc_bare, "main", "arc_fresh")
    assert archive.verify(arc, pub)["result"] == "verified"
    archive.scan(pub)
    assert not archive.ledger_files(pub)
    assert len(ledger.read_all(arc)) == rows0 + 4 * 2  # runs 2 and 4 reached the archive; run 1 did not
    # the public history is not rewritten: the pre-migration commit is still an ancestor of the tip
    assert subprocess.run(["git", "merge-base", "--is-ancestor", pre, "HEAD"], cwd=pub).returncode == 0
    assert "ledger/" in git(pub, "show", "--stat", "--format=", pre)  # and still holds the old files


def test_nothing_is_removed_publicly_until_the_archive_push_succeeded(remotes):
    tmp, pub_bare, arc_bare, pre = remotes
    run(tmp, pub_bare, arc_bare, forecast(1), fail_at="archive_push")
    pub = checkout(tmp, pub_bare, "forecast-data", "pub_check")
    assert git(pub, "rev-parse", "HEAD") == pre and archive.ledger_files(pub)


def reject_pushes(bare, on=True):
    hook = bare / "hooks" / "pre-receive"
    if on:
        hook.write_text("#!/bin/sh\necho 'remote: rejected by test hook' >&2\nexit 1\n")
        hook.chmod(0o755)
    elif hook.exists():
        hook.unlink()


@pytest.mark.parametrize("target", ["archive", "public"])
def test_real_push_rejection_stops_the_run_and_the_next_run_recovers(remotes, target):
    tmp, pub_bare, arc_bare, pre = remotes
    bare = arc_bare if target == "archive" else pub_bare
    reject_pushes(bare)
    with pytest.raises(subprocess.CalledProcessError) as err:
        run(tmp, pub_bare, arc_bare, forecast(1))
    assert "rejected by test hook" in err.value.stderr
    pub = checkout(tmp, pub_bare, "forecast-data", "pub_after_reject")
    assert git(pub, "rev-parse", "HEAD") == pre and archive.ledger_files(pub)  # public untouched
    reject_pushes(bare, on=False)
    run(tmp, pub_bare, arc_bare, forecast(2))
    pub = checkout(tmp, pub_bare, "forecast-data", "pub_ok")
    arc = checkout(tmp, arc_bare, "main", "arc_ok")
    assert archive.verify(arc, pub)["result"] == "verified" and not archive.ledger_files(pub)


def test_non_fast_forward_archive_push_is_refused_then_recovered(remotes):
    tmp, pub_bare, arc_bare, pre = remotes
    run(tmp, pub_bare, arc_bare, forecast(1))  # archive now has history
    pub = checkout(tmp, pub_bare, "forecast-data", "pub")
    arc = checkout(tmp, arc_bare, "main", "arc")
    archive.seed(arc, pub)
    ledger.append(arc, recs(T0 + timedelta(minutes=30)))
    other = checkout(tmp, arc_bare, "main", "concurrent")  # someone else pushes in between
    (other / "note.txt").write_text("concurrent\n")
    commit_push(other, "main", "concurrent")
    with pytest.raises(subprocess.CalledProcessError) as err:
        commit_push(arc, "main", "archive")
    assert "rejected" in err.value.stderr or "fetch first" in err.value.stderr
    pub_tip = git(checkout(tmp, pub_bare, "forecast-data", "pub_tip"), "rev-parse", "HEAD")
    run(tmp, pub_bare, arc_bare, forecast(3))  # the next run starts from the new remote state
    assert git(checkout(tmp, pub_bare, "forecast-data", "pub_tip2"), "rev-parse", "HEAD") != pub_tip
    arc = checkout(tmp, arc_bare, "main", "arc_final")
    assert (arc / "note.txt").exists()  # the concurrent commit was not overwritten


def test_transport_loss_before_the_archive_push_leaves_public_untouched(remotes):
    tmp, pub_bare, arc_bare, pre = remotes
    pub = checkout(tmp, pub_bare, "forecast-data", "pub")
    arc = checkout(tmp, arc_bare, "main", "arc")
    archive.seed(arc, pub)
    git(arc, "remote", "set-url", "origin", str(tmp / "gone.git"))  # remote unreachable
    with pytest.raises(subprocess.CalledProcessError):
        commit_push(arc, "main", "archive")
    assert git(checkout(tmp, pub_bare, "forecast-data", "pub2"), "rev-parse", "HEAD") == pre
