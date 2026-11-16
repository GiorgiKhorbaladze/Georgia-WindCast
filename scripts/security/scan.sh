#!/usr/bin/env bash
# Security scans with explicit gates. Reports go to ./security-reports (git-ignored).
#
#   scripts/security/scan.sh secrets              TruffleHog: full git history + working tree
#   scripts/security/scan.sh semgrep              Semgrep: community rules (pinned) + .semgrep/
#   scripts/security/scan.sh trivy-fs             Trivy: uv.lock, package-lock.json, Dockerfiles, secrets
#   scripts/security/scan.sh trivy-image IMG...   Trivy: OS + library vulnerabilities in images
#
# Gates (release blockers; everything else is reported for triage, see
# docs/security/SECURITY-REPORT.md "Triage process"):
#   secrets      any finding                                  (values are never printed)
#   semgrep      any ERROR-severity finding
#   trivy-fs     HIGH/CRITICAL dependency vulns with a fix; HIGH/CRITICAL misconfig; any secret
#   trivy-image  CRITICAL vulns with a fix (HIGH listed for triage)
# Tools come from scripts/security/install-tools.sh (pinned, verified).
set -euo pipefail
cd "$(dirname "$0")/../.."
T="${SECTOOLS_DIR:-.sectools}"
OUT=security-reports
mkdir -p "$OUT"
export TRIVY_CACHE_DIR="${TRIVY_CACHE_DIR:-$T/trivy-cache}"
# .git: history is scanned by the `trufflehog git` pass (reachable commits); the filesystem pass
# must not read raw object files, which can hold unreachable local leftovers that were never pushed.
EXCLUDES=(.git node_modules .venv .venv-st .venv-col .next .mypy_cache .sectools security-reports
  frontend/public/vendor playwright-report test-results)

secrets() {
  # --no-verification: candidate secrets are never sent to any third-party API.
  # Exit status is checked: a scanner error must fail the gate, never read as "0 findings".
  local rc=0
  "$T/trufflehog" git "file://$PWD" --no-verification --no-update --json \
    2>"$OUT/trufflehog-git.err" >"$OUT/trufflehog-git.jsonl" || rc=$?
  [[ $rc == 0 ]] || { echo "trufflehog git scan failed (rc=$rc)"; tail -5 "$OUT/trufflehog-git.err"; return 2; }
  "$T/trufflehog" filesystem . --no-verification --no-update --json \
    --exclude-paths=<(printf '%s\n' "${EXCLUDES[@]}" | sed 's/^/(^|\\\/)/; s/$/(\\\/|$)/') \
    2>"$OUT/trufflehog-fs.err" >"$OUT/trufflehog-fs.jsonl" || rc=$?
  [[ $rc == 0 ]] || { echo "trufflehog filesystem scan failed (rc=$rc)"; tail -5 "$OUT/trufflehog-fs.err"; return 2; }
  python3 - "$OUT" <<'PY'
import json, sys, pathlib
out = pathlib.Path(sys.argv[1]); total = 0; redacted = []
for name in ("trufflehog-git.jsonl", "trufflehog-fs.jsonl"):
    for line in (out / name).read_text().splitlines():
        if '"DetectorName"' not in line:
            continue
        r = json.loads(line); total += 1
        meta = r.get("SourceMetadata", {}).get("Data", {})
        loc = meta.get("Git") or meta.get("Filesystem") or {}
        # Never print or keep the secret itself: only where and which detector.
        redacted.append({"source": name, "detector": r.get("DetectorName"), "file": loc.get("file"),
                         "line": loc.get("line"), "commit": (loc.get("commit") or "")[:12]})
    (out / name).unlink()  # raw output contains the candidate values: do not keep it
(out / "trufflehog-redacted.json").write_text(json.dumps(redacted, indent=1))
for f in redacted:
    print(f"SECRET CANDIDATE {f['detector']} {f['file']}:{f['line']} {f['commit']}")
print(f"trufflehog: {total} finding(s)")
sys.exit(1 if total else 0)
PY
}

semgrep_scan() {
  local R="$T/semgrep-rules" args=()
  for e in "${EXCLUDES[@]}"; do args+=(--exclude "$e"); done
  "$T/semgrep-venv/bin/semgrep" --metrics=off --disable-version-check --quiet --json \
    -o "$OUT/semgrep.json" "${args[@]}" \
    --config "$R/python" --config "$R/typescript" --config "$R/javascript" \
    --config "$R/dockerfile" --config "$R/yaml/github-actions" --config "$R/bash" \
    --config "$R/generic/secrets" --config .semgrep/ .
  python3 - "$OUT/semgrep.json" <<'PY'
import json, sys
from collections import Counter
d = json.load(open(sys.argv[1]))
if d.get("errors"):
    print(f"semgrep: {len(d['errors'])} scan error(s)"); sys.exit(2)
sev = Counter(r["extra"]["severity"] for r in d["results"])
for r in d["results"]:
    if r["extra"]["severity"] == "ERROR":
        print(f"BLOCKER {r['check_id'].split('.')[-1]} {r['path']}:{r['start']['line']}")
print(f"semgrep: {dict(sev)} over {len(d.get('paths', {}).get('scanned', []))} files")
sys.exit(1 if sev.get("ERROR") else 0)
PY
}

trivy_fs() {
  local skips=() rc=0
  for e in "${EXCLUDES[@]}"; do skips+=(--skip-dirs "$e" --skip-dirs "frontend/$e" --skip-dirs "backend/$e"); done
  "$T/trivy" fs --quiet --scanners vuln,secret,misconfig --format json -o "$OUT/trivy-fs.json" "${skips[@]}" .
  "$T/trivy" fs --quiet --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --ignore-unfixed \
    --exit-code 1 --format table "${skips[@]}" . || rc=$?
  echo "trivy-fs: gate rc=$rc (report: $OUT/trivy-fs.json)"
  return "$rc"
}

trivy_image() {
  local rc=0 img safe
  for img in "$@"; do
    safe="${img//[^A-Za-z0-9._-]/_}"
    "$T/trivy" image --quiet --scanners vuln --format json -o "$OUT/trivy-image-$safe.json" "$img"
    python3 - "$OUT/trivy-image-$safe.json" "$img" <<'PY'
import json, sys
from collections import Counter
d = json.load(open(sys.argv[1])); c = Counter(); fix = Counter()
for r in d.get("Results", []):
    for v in r.get("Vulnerabilities") or []:
        c[v["Severity"]] += 1
        if v.get("FixedVersion"): fix[v["Severity"]] += 1
arch = d.get("Metadata", {}).get("ImageConfig", {}).get("architecture")
print(f"{sys.argv[2]} ({arch}): all={dict(c)} with-fix={dict(fix)}")
PY
    "$T/trivy" image --quiet --scanners vuln --severity CRITICAL --ignore-unfixed --exit-code 1 \
      --format table "$img" || rc=1
  done
  return "$rc"
}

case "${1:-}" in
  secrets) secrets ;;
  semgrep) semgrep_scan ;;
  trivy-fs) trivy_fs ;;
  trivy-image) shift; trivy_image "$@" ;;
  *) echo "usage: $0 secrets|semgrep|trivy-fs|trivy-image IMG..." >&2; exit 2 ;;
esac
