# Caddy (automatic HTTPS) with the rate-limit module, pinned. Multi-arch: builds natively on
# linux/arm64 (OCI Ampere A1) and linux/amd64.
ARG CADDY_VERSION=2.11.9
ARG CADDY_BUILDER_IMAGE=caddy:2.11.9-builder-alpine@sha256:646fee578e680989ca5c7fd1ce6f1de574d19fd71ef2221810cc0510a9f40c86
ARG CADDY_IMAGE=caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0
# golang.org/x/net in Caddy 2.11.9's module graph carries CVE-2026-78661 (fixed in 0.62.0, Trivy
# image scan); xcaddy builds with the fixed version. Remove once Caddy's own release includes it.
ARG XNET_VERSION=v0.62.0

# The Go build runs on the build machine's architecture and cross-compiles for the target, so an
# arm64 image builds quickly on amd64 CI (no emulated compiler).
FROM --platform=$BUILDPLATFORM ${CADDY_BUILDER_IMAGE} AS build
ARG CADDY_VERSION
ARG XNET_VERSION
ARG TARGETOS
ARG TARGETARCH
# Optional build secret "extra_ca" for networks with TLS inspection. No-op if absent.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then cp /run/secrets/extra_ca /usr/local/share/ca-certificates/extra.crt && update-ca-certificates; fi; \
    GOOS="${TARGETOS:-linux}" GOARCH="${TARGETARCH:-amd64}" xcaddy build "v${CADDY_VERSION}" \
      --with github.com/mholt/caddy-ratelimit@v0.1.0 \
      --replace "golang.org/x/net=golang.org/x/net@${XNET_VERSION}"

FROM ${CADDY_IMAGE}
# OS_UPDATES=0 only for networks that cannot reach the Alpine mirrors (a failed upgrade is an
# error, never a silent no-op); CI and real hosts always apply updates.
ARG OS_UPDATES=1
COPY --from=build /usr/bin/caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
# Run as an unprivileged user (Trivy DS-0002). Binding 80/443 needs no capability: compose sets
# the namespaced sysctl net.ipv4.ip_unprivileged_port_start=0 for this container only, so all
# capabilities can be dropped and no-new-privileges enforced.
# The binary must carry NO file capability: with every capability dropped, the kernel refuses to
# exec a file whose required file capabilities exceed the bounding set ("operation not
# permitted"). Rewriting the file drops the security.capability xattr.
RUN --mount=type=secret,id=extra_ca,required=false \
    set -e; \
    if [ "$OS_UPDATES" = 1 ]; then \
      if [ -s /run/secrets/extra_ca ]; then mkdir -p /usr/local/share/ca-certificates; cp /run/secrets/extra_ca /usr/local/share/ca-certificates/extra.crt; update-ca-certificates >/dev/null 2>&1 || true; fi; \
      apk upgrade --no-cache; \
      rm -f /usr/local/share/ca-certificates/extra.crt; update-ca-certificates >/dev/null 2>&1 || true; \
    else echo "WARNING: OS security updates skipped (OS_UPDATES=0)"; fi; \
    cat /usr/bin/caddy > /usr/bin/caddy.new; chmod 0755 /usr/bin/caddy.new; mv /usr/bin/caddy.new /usr/bin/caddy; \
    addgroup -S -g 10002 caddy; adduser -S -D -H -u 10002 -G caddy caddy; \
    mkdir -p /data/caddy /config/caddy; chown -R caddy:caddy /data /config
USER caddy
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:2019/config/ >/dev/null || exit 1
