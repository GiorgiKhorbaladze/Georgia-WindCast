#!/usr/bin/env bash
# Installs the security scanners into ./.sectools (git-ignored) with verified, pinned artifacts.
# Used by .github/workflows/security.yml and for local runs. Linux x86-64 only.
#   scripts/security/install-tools.sh                 all tools
#   scripts/security/install-tools.sh trivy semgrep   only these (trivy implies cosign)
#
# Supply-chain rules (docs/security/SECURITY-REPORT.md, "Tool provenance"):
#   - Every downloaded binary is checked against a SHA-256 pinned in THIS file. No "latest".
#   - Trivy is additionally verified with cosign against Aqua Security's GitHub Actions release
#     identity (the March 2026 compromise, GHSA-69fq-xp46-6x23 / CVE-2026-33634, shipped
#     malicious v0.69.4 binaries and force-pushed trivy-action/setup-trivy tags; this repo uses
#     neither action, only a verified binary). v0.76.2 was signed 2026-11-05 by
#     .github/workflows/reusable-release.yaml@refs/tags/v0.76.2.
#   - cosign itself is checked against the SHA-256 published in its release.
#   - Semgrep runs from PyPI at a pinned version with the community rules repository pinned to a
#     commit; nothing is sent to semgrep.dev (no login, metrics off).
# Updating a tool = change version AND hash here, in a reviewed PR.
set -euo pipefail
cd "$(dirname "$0")/../.."
DEST="${SECTOOLS_DIR:-.sectools}"
mkdir -p "$DEST"

TRIVY_VERSION=0.76.2
TRIVY_SHA256=bc0fc726e017b8927a62b2d3531d7a84ee01769daf5c99ed866dced54089fdbf
COSIGN_VERSION=3.1.4
COSIGN_SHA256=424e2c97d0b45fd7a6b608a87f090f35633f4c23ece5f092d48bba11aaf4bbfa
TRUFFLEHOG_VERSION=3.99.9
TRUFFLEHOG_SHA256=12050095c8063bf4d34f9f6cbce6ba9fa8d0deea9d503d0570364feba093658e
SEMGREP_VERSION=1.185.0
SEMGREP_RULES_COMMIT=a5ad1714f00c9f7fde980cab0ea1d6dc6d414fd2

want="${*:-cosign trivy trufflehog semgrep}"
[[ $want == *trivy* && $want != *cosign* ]] && want="cosign $want"
wants() { [[ " $want " == *" $1 "* ]]; }

fetch() {  # fetch <url> <out> <sha256>
  curl -fsSL --retry 3 -o "$2" "$1"
  echo "$3  $2" | sha256sum -c --quiet - || { echo "CHECKSUM MISMATCH for $1" >&2; rm -f "$2"; exit 1; }
}

if wants cosign; then
echo "== cosign v$COSIGN_VERSION"
fetch "https://github.com/sigstore/cosign/releases/download/v${COSIGN_VERSION}/cosign-linux-amd64" \
  "$DEST/cosign" "$COSIGN_SHA256"
chmod +x "$DEST/cosign"
fi

if wants trivy; then
echo "== trivy v$TRIVY_VERSION (sha256 + cosign identity)"
base="https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}"
tgz="trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz"
fetch "$base/$tgz" "$DEST/$tgz" "$TRIVY_SHA256"
curl -fsSL --retry 3 -o "$DEST/$tgz.sigstore.json" "$base/$tgz.sigstore.json"
trusted_root=()
# Restricted networks without access to Sigstore's TUF CDN can supply a trusted root file.
[[ -n ${COSIGN_TRUSTED_ROOT:-} ]] && trusted_root=(--trusted-root "$COSIGN_TRUSTED_ROOT")
"$DEST/cosign" verify-blob "$DEST/$tgz" --bundle "$DEST/$tgz.sigstore.json" "${trusted_root[@]}" \
  --certificate-identity "https://github.com/aquasecurity/trivy/.github/workflows/reusable-release.yaml@refs/tags/v${TRIVY_VERSION}" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
tar -xzf "$DEST/$tgz" -C "$DEST" trivy
"$DEST/trivy" --version | head -1
fi

if wants trufflehog; then
echo "== trufflehog v$TRUFFLEHOG_VERSION"
th="trufflehog_${TRUFFLEHOG_VERSION}_linux_amd64.tar.gz"
fetch "https://github.com/trufflesecurity/trufflehog/releases/download/v${TRUFFLEHOG_VERSION}/$th" \
  "$DEST/$th" "$TRUFFLEHOG_SHA256"
tar -xzf "$DEST/$th" -C "$DEST" trufflehog
"$DEST/trufflehog" --version 2>&1 | tail -1
fi

if wants semgrep; then
echo "== semgrep $SEMGREP_VERSION + rules @ ${SEMGREP_RULES_COMMIT:0:12}"
python3 -m venv "$DEST/semgrep-venv"
"$DEST/semgrep-venv/bin/pip" install --quiet --disable-pip-version-check "semgrep==${SEMGREP_VERSION}"
if [[ ! -d "$DEST/semgrep-rules/.git" ]]; then
  git init -q "$DEST/semgrep-rules"
  git -C "$DEST/semgrep-rules" remote add origin https://github.com/semgrep/semgrep-rules.git
fi
git -C "$DEST/semgrep-rules" fetch -q --depth 1 origin "$SEMGREP_RULES_COMMIT"
git -C "$DEST/semgrep-rules" checkout -q --detach FETCH_HEAD
[[ $(git -C "$DEST/semgrep-rules" rev-parse HEAD) == "$SEMGREP_RULES_COMMIT" ]]
"$DEST/semgrep-venv/bin/semgrep" --version
fi
echo "tools ready in $DEST: $want"
