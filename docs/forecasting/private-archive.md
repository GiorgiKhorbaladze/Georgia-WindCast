# Private forecast archive

Owner decision of 21.11.2026: numeric MW forecasts are not stored in the clear on the public
`forecast-data` branch. They are not published after their validity period ends either; that would
need a separate owner decision. `mwmodel.PUBLISH_FORECAST` stays `False`.

## What goes where

| Content | Private archive repository | Public `forecast-data` |
|---|---|---|
| Live ledger `ledger/**` (all `prediction_mw`, q10/q90) | yes | no |
| Backtest ledger `backtest/ledger/**` | yes | no |
| `state.json`, `evaluation/latest.csv` | yes | no |
| Day-ahead energy rows `evaluation/day_ahead_*.csv` | yes | no; only `day_ahead_summary_*.json` (MAE and day count per model) |
| Tournament predictions `evaluation/tournament_*.csv.gz` | yes | no; only `tournament.json` (scores) |
| Daily accuracy `history_*.csv` | yes | yes, without the per-day `bias` column |
| `leaderboard.json`, `tournament.json` | yes | yes, with MAE, RMSE, skill and counts; **no bias at any level** |
| Commitments `commitments/ledger.json` | n/a | yes |
| Weather inputs `weather/**` | no | yes (not MW forecasts) |

Bias is never published. With the public GSE actuals, bias over a set of cases gives back the
mean forecast for exactly those cases. A leaderboard or tournament row can cover a single day,
so its bias would be that day's mean forecast (QA finding AR2). `publish` strips `bias` at every
level of every public JSON file, and the scan refuses it anywhere. Score rows (any object with a
`model_id`) may only carry a fixed set of keys. MAE, RMSE and skill cannot be inverted to recover
a forecast.

## Why a private repository, not encrypted files on the public branch

| Criterion | Private GitHub repository (chosen) | Encrypted files on the public branch |
|---|---|---|
| Security | Values never leave GitHub's access control. A leaked deploy key can be revoked; the data were never public. | Ciphertext is public forever. A key leak at any point exposes the whole history, and it cannot be undone. |
| Cost | Free (private repositories are free; about 2 MB today) | Free |
| Key management | One deploy key, scoped to one repository, revocable and rotatable in two clicks. Losing it loses no data. | One symmetric key. Losing it loses the entire archive. It must be backed up outside GitHub. |
| Recovery | `git clone` of the private repository. GitHub keeps it. | Needs the key and the code version that encrypted it. |
| Independent verification | Public hash commitments, time-stamped by the public git history. Hand the archive to a reviewer, who runs `verify`. | Same commitments possible. Verification also needs the key to be handed over. |
| Moving parts | Plain git. No cryptography in this repository. | Cryptographic code and format versioning to maintain. |

A private repository is safer, because nothing private is ever published. It is also simpler to
run, because it needs no cryptography and losing a key loses no data.

## One-time setup (owner)

1. Create a private repository, e.g. `GiorgiKhorbaladze/Georgia-WindCast-forecast-archive`.
   Leave it empty, with no README. The first run seeds it from the current public ledger.
2. On your own computer: `ssh-keygen -t ed25519 -N "" -C windcast-archive -f windcast_archive`.
3. In the private repository, go to Settings → Deploy keys → Add deploy key. Paste
   `windcast_archive.pub` and tick **Allow write access**.
4. Create a **fine-grained personal access token**, used only to prove privacy:
   * Settings → Developer settings → Fine-grained tokens;
   * Repository access: *Only select repositories*, then choose the archive repository;
   * Permissions: Repository → **Metadata: Read-only**, and nothing else;
   * Expiry: up to one year, with a calendar reminder to renew it.

   This token cannot read or write content; it can only read the repository's visibility.
5. In this repository, go to Settings → Secrets and variables → Actions:
   * Secrets: `FORECAST_ARCHIVE_SSH_KEY` = the content of `windcast_archive` (the private key).
   * Secrets: `FORECAST_ARCHIVE_METADATA_TOKEN` = the token from step 4.
   * Variables: `FORECAST_ARCHIVE_REPO` = `GiorgiKhorbaladze/Georgia-WindCast-forecast-archive`.
6. Delete both local key files. A lost key is replaced, not recovered (see Rotation).

Until all three are set, `forecast.yml` and `forecast-tournament.yml` stop before issuing anything,
so a missing archive can never cause values to be written publicly. GSE collection is a separate
workflow and is not affected.

## How a run works

Both `forecast.yml` and `forecast-tournament.yml` run the same sequence, so runs can come in any
order:

1. The archive is cloned over SSH, with GitHub's published ed25519 host key pinned.
   `git ls-remote` must succeed. An unknown or unreachable repository stops the run; there is no
   fallback that would create an empty branch.
2. `check-private`: positive proof only. `GET /repos/{archive}`, made with the metadata token, must
   return **200** with `private: true`, `visibility: private` and the same full name. Any of the
   following stops the run before anything is written:
   * 404, which can also mean a typo, a deleted repository or a token without access;
   * 401, 403 or 5xx;
   * a missing token;
   * an answer for another repository, or this public repository itself.
3. `seed` absorbs every private file still on the public side into the archive, and each copy is
   checked by SHA-256. A ledger present in both places must be a byte prefix of the archived one;
   otherwise the run stops instead of guessing.
4. `verify`: every committed ledger file must be an exact byte prefix of its archived file
   (append-only gzip). A missing or altered file stops the run.
5. Forecasts or tournament predictions are written into the archive, and the archive is pushed
   **first**.
6. `publish` runs `covered` first. It refuses to remove any public file the archive does not hold
   (QA finding AR1). It then writes the projection and runs the allowlist scan (QA finding AR2):
   * outside `weather/`, only the listed files may exist;
   * `history_*.csv` may only have the columns `day, cadence, horizon_min, model_id, cases, mae, rmse`;
   * in public JSON, every number must sit under a score, count or provenance key, such as `mae`,
     `rmse`, `skill`, `cases`, `days` or `run_id`. A number under any other key, a number hidden in
     a string, a forecast key or `bias`, or a score row with an unexpected key stops the run.
7. The public branch is pushed.

### Time evidence

A git commit date is set by whoever commits, so on its own it is not proof of time. Every
publish therefore appends a line to `commitments/runs.jsonl` with:
* the SHA-256 of `commitments/ledger.json`;
* the GitHub Actions `run_id` and `run_attempt`, and the workflow name;
* the private archive commit SHA.

GitHub records the run's creation and start times itself
(`GET /repos/{repo}/actions/runs/{run_id}`), and the repository cannot alter them. The same digest
is also printed in the public run log. Limits: run logs are kept for 90 days, while the run
metadata stays as long as the run is not deleted by an administrator. This is strong evidence,
not a third-party timestamping service.

## Safe migration procedure (owner approval needed at steps 1 and 4)

1. **Create the private repository** and keep it empty. Add the deploy key with write access,
   the secrets `FORECAST_ARCHIVE_SSH_KEY` and `FORECAST_ARCHIVE_METADATA_TOKEN`, and the variable
   `FORECAST_ARCHIVE_REPO` (see One-time setup).
   Nothing runs yet: the old `forecast.yml` on `main` does not read these.
2. **Pre-merge check (no write)**: in the private repository, Settings → General, confirm the
   visibility is *Private*. On the public repository, open the PR's CI.
3. **Backup point**: note the current `forecast-data` head SHA. The branch history is not rewritten,
   so every pre-migration file stays reachable at that SHA, which makes a full rollback possible.
4. **Merge PR #69** (owner decision). The next `forecast.yml` run, about 15 minutes later after a
   GSE collection, does the following:
   check-private → seed (21 files today) → verify → issue → push archive → covered → publish
   (removes `ledger/`, `backtest/`, `state.json`, `latest.csv` and `day_ahead_*.csv` from the
   public tip in a normal commit) → push public.
   If any step fails, nothing is removed from the public side. A failure before the archive push
   leaves both sides unchanged. A failure after it leaves the archive ahead, and the next run
   completes the step.
5. **Check after the first run**:
   * the archive holds `ledger/`, `backtest/` and `state.json`;
   * `forecast-data` has `commitments/ledger.json` and `runs.jsonl`, and no `ledger/`;
   * the page's scores are unchanged.
6. **Rollback (QA finding AR3). Do not revert this change.** A revert restores the old
   `forecast.yml`, which writes the ledger and `latest.csv` to the public branch again on its very
   next run, about 15 minutes after a GSE collection. Instead:
   * **Pause**: set the repository variable `FORECAST_PAUSED=true`. Both forecast jobs are then
     skipped at their first line. GSE collection keeps running; nothing is written anywhere.
   * **Fix forward** in a new PR. The archive keeps every record.
   * If the code must still be reverted, first disable `forecast.yml` and `forecast-tournament.yml`
     (Actions → workflow → ⋯ → Disable workflow), then revert, and re-enable only after a fix that
     keeps values private.
   * Putting the old public files back would publish values again and needs a separate owner decision.

## Rotation, recovery, verification

* Rotation: add a new deploy key, replace the secret, then delete the old deploy key.
* Recovery: `git clone git@github.com:<owner>/<archive>.git`. To rebuild the public projection
  from the archive alone, run `python -m forecasting.run publish --out-dir ARCHIVE --public-dir PUBLIC`.
* Verification by a third party, given read access to the archive:
  `python -m forecasting.run verify --out-dir ARCHIVE --public-dir <forecast-data checkout at a past commit>`.
  To date a state of the archive, use the GitHub Actions run recorded with it in
  `commitments/runs.jsonl` (see Time evidence), not the commit date.

## Values already in the public history

Before this change, `forecast-data` held the ledgers, `latest.csv` and day-ahead energy rows in
the clear (Issue #57 stage I, from 20.11.2026). By owner decision the git history is **not**
rewritten. Those commits remain reachable by anyone through their commit SHAs, the GitHub
API and raw file URLs. Clones, forks and caches made in the meantime cannot be recalled even by a
history rewrite.

**Not all of them are in the past.** The longest horizon is 48 h (1-hour cadence). Every
pre-migration commit therefore holds forecasts for up to 48 hours after that commit. On 21.11.2026
the public ledger reached valid periods up to 23.11.2026 12:00 UTC. The last public commit before
the migration will hold forecasts for periods up to 48 hours after the migration run. Those values
remain readable in the public history until their periods have passed, and after that as past
forecasts. Rewriting the branch would need a force-push and a separate owner decision. Even a
rewrite would not recall copies already made.

Note that the stage I baselines (persistence, damped trend, climatology) are deterministic
functions of public GSE data and open code. Withholding their values is about not publishing
forecasts, not about secrecy of the method.
