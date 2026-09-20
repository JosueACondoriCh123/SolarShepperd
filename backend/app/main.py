from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.operational import router as operational_router
from app.api.router import router
from app.config import get_settings
from app.db import SessionLocal, database_ready
from app.errors import register_error_handlers
from app.logging import configure_logging
from app.models import SystemState
from app.services.object_storage import ObjectStorage

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.environment == "production" and settings.auth_mode != "supabase":
        raise RuntimeError("AUTH_MODE must be 'supabase' in production")
    if settings.auth_mode == "supabase" and not settings.supabase_configured:
        raise RuntimeError("SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY are required")
    if settings.auth_mode == "supabase":
        if not settings.supabase_secret_key:
            raise RuntimeError("SUPABASE_SECRET_KEY is required for private Storage")
        try:
            await ObjectStorage(settings).ensure_private_buckets()
        except Exception as exc:
            logger.warning("storage_bucket_setup_failed", error_type=type(exc).__name__)
    logger.info(
        "application_starting", environment=settings.environment, version=settings.app_version
    )
    yield
    logger.info("application_stopping")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Climate intelligence and transparent pastoral routing using real telemetry, "
        "Earth observation and terrain data."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Token", "If-Match"],
)
register_error_handlers(app)
app.include_router(router)
app.include_router(operational_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "version": settings.app_version, "docs": "/docs"}


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version}


async def _readiness_response() -> JSONResponse:
    database_ok = await database_ready()
    redis_ok = False
    try:
        client = redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        redis_ok = bool(await client.ping())
        await client.aclose()
    except Exception:
        redis_ok = False
    worker_ok = False
    heartbeat_at: str | None = None
    if database_ok:
        try:
            async with SessionLocal() as session:
                heartbeat = await session.get(SystemState, "worker_heartbeat")
                heartbeat_at = heartbeat.value.get("observed_at") if heartbeat else None
                if heartbeat_at:
                    parsed = datetime.fromisoformat(heartbeat_at)
                    worker_ok = datetime.now(UTC) - parsed.astimezone(UTC) <= timedelta(minutes=3)
        except Exception:
            worker_ok = False
    ready = database_ok and redis_ok and worker_ok
    payload = {
        "status": "ok" if ready else "degraded",
        "version": settings.app_version,
        "checks": {
            "database": database_ok,
            "redis": redis_ok,
            "worker": worker_ok,
            "worker_heartbeat_at": heartbeat_at,
        },
    }
    return JSONResponse(status_code=200 if ready else 503, content=payload)


@app.get("/health/ready")
async def health_ready() -> JSONResponse:
    return await _readiness_response()


@app.get("/health")
async def health() -> JSONResponse:
    return await _readiness_response()
