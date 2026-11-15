# Caddy (automatic HTTPS) with the rate-limit module, pinned. Multi-arch: builds natively on
# linux/arm64 (OCI Ampere A1) and linux/amd64.
ARG CADDY_VERSION=2.11.9
ARG CADDY_BUILDER_IMAGE=caddy:2.11.9-builder-alpine
ARG CADDY_IMAGE=caddy:2.11.9-alpine

# The Go build runs on the build machine's architecture and cross-compiles for the target, so an
# arm64 image builds quickly on amd64 CI (no emulated compiler).
FROM --platform=$BUILDPLATFORM ${CADDY_BUILDER_IMAGE} AS build
ARG CADDY_VERSION
ARG TARGETOS
ARG TARGETARCH
# Optional build secret "extra_ca" for networks with TLS inspection. No-op if absent.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then cp /run/secrets/extra_ca /usr/local/share/ca-certificates/extra.crt && update-ca-certificates; fi; \
    GOOS="${TARGETOS:-linux}" GOARCH="${TARGETARCH:-amd64}" xcaddy build "v${CADDY_VERSION}" --with github.com/mholt/caddy-ratelimit@v0.1.0

FROM ${CADDY_IMAGE}
COPY --from=build /usr/bin/caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
