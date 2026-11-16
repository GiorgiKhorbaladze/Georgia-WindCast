# PostgreSQL for WindCast: the official image, hardened (docs/security/THREAT-MODEL.md).
# - Runs as the unprivileged "postgres" user from the first instruction: the entrypoint never
#   starts as root, so the container needs no Linux capability at all.
# - gosu (only used by the entrypoint to drop root) is removed: never executed here, and its
#   bundled Go runtime carried CRITICAL/HIGH findings (Trivy: stdlib v1.24.6, CVE-2025-68121).
# - Alpine security updates applied on top of the pinned base.
# The data directory in the base image is owned by postgres, so new named volumes inherit it.
ARG POSTGRES_IMAGE=postgres:17.12-alpine3.24@sha256:a77aa70e641402a21411b92b721c58d10f23b50ae5fdd2333efd22d166e1e5f7
FROM ${POSTGRES_IMAGE}
# OS_UPDATES=0 only for networks that cannot reach the Alpine mirrors (a failed upgrade is an
# error, never a silent no-op); CI and real hosts always apply updates.
ARG OS_UPDATES=1
RUN --mount=type=secret,id=extra_ca,required=false \
    set -e; \
    if [ "$OS_UPDATES" = 1 ]; then \
      if [ -s /run/secrets/extra_ca ]; then mkdir -p /usr/local/share/ca-certificates; cp /run/secrets/extra_ca /usr/local/share/ca-certificates/extra.crt; update-ca-certificates >/dev/null 2>&1 || true; fi; \
      apk upgrade --no-cache; \
      rm -f /usr/local/share/ca-certificates/extra.crt; update-ca-certificates >/dev/null 2>&1 || true; \
    else echo "WARNING: OS security updates skipped (OS_UPDATES=0)"; fi; \
    rm -f /usr/local/bin/gosu
USER postgres
