ARG PYTHON_IMAGE=python:3.12.16-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# Build stage: uv resolves the locked dependencies into /opt/venv. uv itself never reaches the
# runtime image (security review: Trivy flagged uv in the runtime layer, GHSA-hq85-5cpj-mr62).
FROM ${PYTHON_IMAGE} AS build
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
# Optional build secret "extra_ca": a PEM bundle for networks with TLS inspection. No-op if absent.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-cache-dir uv==0.11.32
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    uv sync --frozen --no-dev --no-install-project

# Runtime stage: same base (the venv's interpreter links resolve), OS security updates applied,
# only the application and its virtualenv.
FROM ${PYTHON_IMAGE} AS runtime
# OS_UPDATES=0 only for networks that cannot reach the Debian mirrors (a failed update is an error,
# never a silent no-op); CI and real hosts always apply updates.
ARG OS_UPDATES=1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
RUN --mount=type=secret,id=extra_ca,required=false \
    set -e; \
    if [ "$OS_UPDATES" = 1 ]; then \
      if [ -s /run/secrets/extra_ca ]; then cp /run/secrets/extra_ca /usr/local/share/ca-certificates/extra.crt && update-ca-certificates >/dev/null; fi; \
      sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
      apt-get update --error-on=any; \
      apt-get upgrade -y --no-install-recommends; \
      rm -rf /var/lib/apt/lists/* /usr/local/share/ca-certificates/extra.crt; \
      update-ca-certificates --fresh >/dev/null; \
    else echo "WARNING: OS security updates skipped (OS_UPDATES=0)"; fi; \
    useradd --system --uid 10001 windcast
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
USER windcast
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status==200 else 1)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --log-level \"$(echo ${WINDCAST_LOG_LEVEL:-info} | tr A-Z a-z)\""]
