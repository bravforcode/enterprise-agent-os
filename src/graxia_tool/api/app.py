"""Enterprise Agent OS — FastAPI application."""
from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings
from .core.database import init_db, close_db
from .core.logging import setup_logging, get_logger
from .observability.prometheus import (
    get_metrics,
    get_metrics_content_type,
    init_system_info,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    setup_logging()
    logger = get_logger("startup")
    logger.info("starting", app=settings.app_name, version=settings.app_version)

    # Init database
    await init_db()
    logger.info("database_ready")

    # Init metrics
    init_system_info(version=settings.app_version)
    logger.info("metrics_ready")

    yield

    # Shutdown
    await close_db()
    logger.info("shutdown")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health Check ---
@app.get("/health")
async def health_check():
    """Health check endpoint for Docker/k8s/load balancer."""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "environment": settings.environment,
    }


@app.get("/health/ready")
async def readiness_check():
    """Readiness probe — checks DB + Redis connectivity."""
    from sqlalchemy import text
    from .core.database import async_session_factory
    import redis.asyncio as aioredis

    checks = {}

    # Database
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    healthy = all(v == "ok" for v in checks.values())
    return {
        "status": "ready" if healthy else "degraded",
        "checks": checks,
    }


@app.get("/health/live")
async def liveness_check():
    """Liveness probe — just confirms process is alive."""
    return {"status": "alive"}


# --- API Routes (Phase 1) ---
from .routes_v1 import router as v1_router
app.include_router(v1_router)

# --- API Routes (Phase 8: Multi-Agent) ---
from .routes_multi_agent import router as multi_agent_router
app.include_router(multi_agent_router)

# --- API Routes (Phase 12: End-to-End Pipeline) ---
from .routes_pipeline import router as pipeline_router
app.include_router(pipeline_router)

# --- API Routes (Phase 14: Web UI) ---
from .routes_ui import router as ui_router
app.include_router(ui_router)


# --- Metrics Endpoint (Phase 10) ---
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=get_metrics(),
        media_type=get_metrics_content_type(),
    )


@app.get("/api/v1/status")
async def api_status():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "modules": [
            "intent-router",
            "orchestrator",
            "skill-registry",
            "tool-registry",
            "token-budget",
            "memory-os",
            "rag-os",
            "guardrails",
            "observability",
        ],
    }
