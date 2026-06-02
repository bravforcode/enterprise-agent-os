"""Enterprise Agent OS — FastAPI application."""
from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings
from .core.database import init_db, close_db
from .core.logging import setup_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    setup_logging()
    logger = get_logger("startup")
    logger.info("starting", app=settings.app_name, version=settings.app_version)

    # Init database
    await init_db()
    logger.info("database_ready")

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
