# WindCast backend

FastAPI read API (`app.main`), scheduled ingestion worker (`app.worker`) and Alembic migrations.
See the repository root README for running the full stack.

```bash
uv sync
uv run alembic upgrade head          # uses WINDCAST_DATABASE_URL
uv run uvicorn app.main:app --reload
uv run python -m app.worker
TEST_DATABASE_URL=postgresql+psycopg://... uv run pytest
```
