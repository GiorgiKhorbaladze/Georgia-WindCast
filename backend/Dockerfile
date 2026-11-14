FROM ghcr.io/astral-sh/uv:0.9.9 AS uv
FROM python:3.12.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY --chown=10001:10001 . .
RUN uv sync --frozen --no-dev && useradd --uid 10001 --create-home windcast
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER windcast
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
