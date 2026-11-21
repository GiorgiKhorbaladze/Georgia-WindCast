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
| `leaderboard.json` | yes | yes (MAE, RMSE, and bias averaged over the whole window per horizon) |
| Commitments `commitments/ledger.json` | n/a | yes |
| Weather inputs `weather/**` | no | yes (not MW forecasts) |

Per-day bias is removed because, with the public GSE actuals, it gives back the day's mean
forecast. The whole-window bias in `leaderboard.json` and `tournament.json` remains. It is a mean
over many days, not a forecast for any period. If even that should be withheld, it is a one-line
change: add the two files to the scan.

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
4. In this repository, go to Settings → Secrets and variables → Actions:
   * Secrets: `FORECAST_ARCHIVE_SSH_KEY` = the content of `windcast_archive` (the private key).
   * Variables: `FORECAST_ARCHIVE_REPO` = `GiorgiKhorbaladze/Georgia-WindCast-forecast-archive`.
5. Delete both local key files. A lost key is replaced, not recovered (see Rotation).

Until both are set, `forecast.yml` and `forecast-tournament.yml` stop before issuing anything,
so a missing archive can never cause values to be written publicly. GSE collection is a separate
workflow and is not affected.

## How a run works

1. The archive is cloned over SSH, with GitHub's published ed25519 host key pinned.
2. `seed` runs once: if the archive is empty, the old public ledger is copied in, and every file
   is checked by SHA-256.
3. `verify` checks that every committed ledger file is an exact byte prefix of its archived file
   (the files are append-only gzip). A missing or altered file stops the run.
4. Forecasts are issued and scored into the archive, and the archive is pushed **first**.
5. `publish` writes the public projection and runs a leak scan. The scan refuses a forbidden path,
   or a forecast column outside the two whole-window aggregate files. Then the public branch is
   pushed.

If the run is interrupted after step 4, the archive is a little ahead of the public commitments.
The next run still verifies, because the commitments are a prefix, and it republishes. If the run
is interrupted before step 4, nothing has changed anywhere.

## Rotation, recovery, verification

* Rotation: add a new deploy key, replace the secret, then delete the old deploy key.
* Recovery: `git clone git@github.com:<owner>/<archive>.git`. To rebuild the public projection
  from the archive alone, run `python -m forecasting.run publish --out-dir ARCHIVE --public-dir PUBLIC`.
* Verification by a third party, given read access to the archive:
  `python -m forecasting.run verify --out-dir ARCHIVE --public-dir <forecast-data checkout at a past commit>`.
  The public commit date of `commitments/ledger.json` shows when that state of the archive existed.

## Values already in the public history

Before this change, `forecast-data` held the ledgers, `latest.csv` and day-ahead energy rows in
the clear (Issue #57 stage I, from 20.11.2026). By owner decision the git history is **not**
rewritten. Those commits remain reachable by anyone through their commit SHAs, the GitHub
API and raw file URLs. Clones, forks and caches made in the meantime cannot be recalled even by a
history rewrite. Every forecast in them targets a period that has already passed. Rewriting
the branch would need a force-push and a separate owner decision.

Note that the stage I baselines (persistence, damped trend, climatology) are deterministic
functions of public GSE data and open code. Withholding their values is about not publishing
forecasts, not about secrecy of the method.
