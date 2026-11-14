"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, v1
from app.config import get_settings
from app.version import __version__


def create_app() -> FastAPI:
    settings = get_settings()  # fails fast on invalid configuration
    app = FastAPI(
        title="Georgia WindCast API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET"],
        )
    app.include_router(health.router)
    app.include_router(v1.router)
    return app


app = create_app()
