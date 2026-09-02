"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cold_chain.api.routes import data, health, jobs, pipeline, waves


def create_app() -> FastAPI:
    app = FastAPI(
        title="GCC Cold-Chain Pipeline API",
        description="HTTP API for wave planning, generation, Gate A/B evaluation, and corpus reads.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(waves.router)
    app.include_router(data.router)
    app.include_router(pipeline.router)
    app.include_router(jobs.router)

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "service": "gcc-cold-chain-pipeline",
            "docs": "/docs",
            "health": "/health",
            "ready": "/ready",
        }

    return app
