ARG NODE_IMAGE=node:22.23.5-alpine3.24@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a
FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# Optional build secret "extra_ca": a PEM bundle for networks with TLS inspection. No-op if absent.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi; \
    npm ci --no-audit --no-fund

FROM ${NODE_IMAGE} AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM ${NODE_IMAGE} AS runtime
# OS_UPDATES=0 only for networks that cannot reach the Alpine mirrors (a failed upgrade is an
# error, never a silent no-op); CI and real hosts always apply updates.
ARG OS_UPDATES=1
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
# OS security updates; the runtime never installs packages, so the image's bundled npm/npx,
# corepack and yarn are removed (security review: Trivy HIGH findings were all inside the global
# npm, e.g. brace-expansion, picomatch, pacote, sigstore - not in the application).
RUN --mount=type=secret,id=extra_ca,required=false \
    set -e; \
    if [ "$OS_UPDATES" = 1 ]; then \
      if [ -s /run/secrets/extra_ca ]; then mkdir -p /usr/local/share/ca-certificates; cp /run/secrets/extra_ca /usr/local/share/ca-certificates/extra.crt; update-ca-certificates >/dev/null 2>&1 || true; fi; \
      apk upgrade --no-cache; \
      rm -f /usr/local/share/ca-certificates/extra.crt; update-ca-certificates >/dev/null 2>&1 || true; \
    else echo "WARNING: OS security updates skipped (OS_UPDATES=0)"; fi; \
    rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
      /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
      /usr/local/bin/yarn /usr/local/bin/yarnpkg /opt/yarn-*; \
    addgroup -S -g 10001 windcast; adduser -S -u 10001 -G windcast windcast
COPY --from=build --chown=windcast:windcast /app/.next/standalone ./
COPY --from=build --chown=windcast:windcast /app/.next/static ./.next/static
COPY --from=build --chown=windcast:windcast /app/public ./public
USER windcast
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD wget -qO- http://127.0.0.1:3000/healthz >/dev/null || exit 1
CMD ["node", "server.js"]
