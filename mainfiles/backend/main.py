"""
main.py — application entrypoint. Run with:
    uvicorn main:app --reload --port 8001
"""
import sys
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# --- Structured Logging (loguru) ---
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from .api import public_router
from .api import router as api_router
from .auth import get_current_user, verify_csrf
from .auth import router as auth_router
from .config import BASE_DIR, settings
from .database import init_db
from .middleware.request_id import RequestIDMiddleware
from .ratelimit import RateLimitMiddleware
from .skills.api_skills import router as skills_router

# Configure loguru for production-ready structured logs
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True,
)
# Also log to file with rotation for persistence
logger.add(
    BASE_DIR / "logs" / "app.log",
    rotation="10 MB",
    retention="7 days",
    compression="gz",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request/response with timing and request ID for traceability."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Use request ID from RequestIDMiddleware (already in request.state)
        request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        start_time = time.perf_counter()

        # Log incoming request
        logger.info(
            "Request started | method={method} path={path} request_id={request_id} client={client}",
            method=request.method,
            path=request.url.path,
            request_id=request_id,
            client=request.client.host if request.client else "unknown",
        )

        try:
            response = await call_next(request)
        except Exception:
            process_time = time.perf_counter() - start_time
            logger.exception(
                "Request failed | method={method} path={path} request_id={request_id} duration_ms={duration_ms:.2f}",
                method=request.method,
                path=request.url.path,
                request_id=request_id,
                duration_ms=process_time * 1000,
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "request_id": request_id},
            )

        process_time = time.perf_counter() - start_time
        logger.info(
            "Request completed | method={method} path={path} request_id={request_id} status={status} duration_ms={duration_ms:.2f}",
            method=request.method,
            path=request.url.path,
            request_id=request_id,
            status=response.status_code,
            duration_ms=process_time * 1000,
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{process_time:.4f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    This factory function allows tests to create an app instance after
    test-specific settings (e.g., DATABASE_URL) have been applied.
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Ensure required directories exist
        settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        (BASE_DIR / "history").mkdir(parents=True, exist_ok=True)
        (BASE_DIR / "logs").mkdir(parents=True, exist_ok=True)
        await init_db()
        # Foundation F1/F2: unify tools + skills into the extension registry.
        # Best-effort — the API works even if extension init fails.
        try:
            from .extensions import initialize_extensions
            initialize_extensions()
            logger.info("Extensions initialized")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Extension init skipped: {exc}")
        # Memory++: project long-term memory into the extension registry.
        try:
            from .memory import register_memory_extension
            if register_memory_extension():
                logger.info("Memory extension registered")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Memory extension skipped: {exc}")
        # Voice: project voice I/O into the extension registry.
        try:
            from .voice import register_voice_extension
            if register_voice_extension():
                logger.info("Voice extension registered")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Voice extension skipped: {exc}")
        # Image generation: project into the extension registry.
        try:
            from .image_gen import register_image_gen_extension
            if register_image_gen_extension():
                logger.info("Image-gen extension registered")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Image-gen extension skipped: {exc}")
        # Skill packs: project bundled packs into the extension registry.
        try:
            from .skills.packs import register_pack_extensions
            count = register_pack_extensions()
            if count:
                logger.info("Registered %d skill packs", count)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Skill pack registration skipped: {exc}")
        # Multi-agent teams: project into the extension registry.
        try:
            from .teams import register_teams_extension
            if register_teams_extension():
                logger.info("Teams extension registered")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Teams extension skipped: {exc}")
        # Learning mode: project into the extension registry.
        try:
            from .learn import register_learn_extension
            if register_learn_extension():
                logger.info("Learn extension registered")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Learn extension skipped: {exc}")
        # Response quality: project into the extension registry.
        try:
            from .response_quality import register_quality_extension
            if register_quality_extension():
                logger.info("Response-quality extension registered")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Response-quality extension skipped: {exc}")
        # Foundation F3: connect configured MCP servers (best-effort).
        if settings.FEATURE_MCP:
            try:
                from .mcp.bridge import setup_mcp_servers
                configs = settings.mcp_server_configs()
                if configs:
                    connected = await setup_mcp_servers(configs)
                    logger.info(f"MCP servers connected: {connected}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"MCP setup skipped: {exc}")
        logger.info("Application startup complete")
        yield
        # Cleanup auto-started Ollama process (if any)
        from .llm import _cleanup_ollama
        _cleanup_ollama()
        # Close the rate-limit store (Redis connection, if any)
        from .ratelimit_redis import close_rate_limit_store
        await close_rate_limit_store()
        # Foundation F3: close MCP server connections.
        try:
            from .mcp.bridge import shutdown_mcp_servers
            await shutdown_mcp_servers()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"MCP shutdown skipped: {exc}")
        logger.info("Application shutdown")

    app = FastAPI(
        title=settings.APP_NAME,
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    # Add security headers (applied to every response)
    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Callable) -> Response:
            response = await call_next(request)

            # Content Security Policy - strict but allows inline scripts/styles for SPA
            # 'unsafe-eval' needed for some JS frameworks; 'unsafe-inline' for inline event handlers/styles
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com; "
                "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
                "img-src 'self' data: blob:; "
                "font-src 'self' data:; "
                "connect-src 'self' http://127.0.0.1:8001 http://localhost:8001 ws:; "
                "object-src 'none'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            )

            # Additional security headers
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = (
                "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
                "magnetometer=(), microphone=(), payment=(), usb=()"
            )

            # HSTS - only in production
            if settings.ENV == "production":
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

            return response

    # Request logging middleware (innermost - runs SECOND on request, after request_id is set)
    app.add_middleware(RequestLoggingMiddleware)

    # Request ID middleware (outermost - runs FIRST on request to set request.state.request_id)
    app.add_middleware(RequestIDMiddleware)

    # Security headers middleware (sets CSP and other response headers)
    app.add_middleware(SecurityHeadersMiddleware)

    # Add rate limiting middleware
    app.add_middleware(RateLimitMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add CSRF validation middleware (after CORS, before protected routes)
    @app.middleware("http")
    async def csrf_middleware(request: Request, call_next):
        try:
            await verify_csrf(request)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )
        return await call_next(request)


    # Public endpoints first (no auth required)
    app.include_router(public_router, prefix=settings.API_PREFIX)
    app.include_router(auth_router, prefix=settings.API_PREFIX)
    # Protected endpoints (require valid Bearer token)
    app.include_router(api_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])
    app.include_router(skills_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])

    # Foundation F6: versioned API aliases. /api/v1/* mirrors /api/* so future
    # breaking changes can ship under /api/v2 while clients migrate.
    api_v1 = f"/api/{settings.API_VERSION}"
    app.include_router(public_router, prefix=api_v1)
    app.include_router(auth_router, prefix=api_v1)
    app.include_router(api_router, prefix=api_v1, dependencies=[Depends(get_current_user)])
    app.include_router(skills_router, prefix=api_v1, dependencies=[Depends(get_current_user)])

    # --- Enhanced Health Endpoint ---
    @app.get("/health")
    async def health_check():
        """Comprehensive health check with dependency status."""
        import httpx
        from sqlalchemy import text

        from .database import engine

        checks = {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": "1.0.0",
            "database": "unknown",
            "ollama": "unknown",
        }
        # Foundation: API version + feature flags. Mock-safe: when settings is
        # a test double (MagicMock), degrade to JSON-safe defaults instead of
        # leaking mock objects into the response body.
        api_version = getattr(settings, "API_VERSION", "v1")
        checks["api_version"] = api_version if isinstance(api_version, str) else "v1"
        try:
            flags = settings.feature_flags() if hasattr(settings, "feature_flags") else {}
            checks["features"] = (
                {str(k): bool(v) for k, v in flags.items()}
                if isinstance(flags, dict) else {}
            )
        except Exception:  # noqa: BLE001 — health must never 500 on flags
            checks["features"] = {}

        # Check database
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "connected"
        except Exception as exc:
            checks["database"] = f"error: {exc}"
            checks["status"] = "degraded"

        # Check Ollama (if configured)
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
                if resp.status_code == 200:
                    checks["ollama"] = "connected"
                else:
                    checks["ollama"] = f"http_{resp.status_code}"
        except Exception:
            checks["ollama"] = "unreachable"

        # Foundation: extension registry status
        try:
            from .extensions import extensions as _extensions
            checks["extensions"] = {
                "registered": len(_extensions.list_all()),
                "enabled": len(_extensions.list_enabled()),
            }
        except Exception:
            checks["extensions"] = "unavailable"

        # Foundation: MCP servers
        try:
            from .mcp.bridge import _clients as _mcp_clients
            checks["mcp_servers"] = sorted(_mcp_clients.keys())
        except Exception:
            checks["mcp_servers"] = "unavailable"

        # Foundation: provider circuit breakers
        try:
            from .providers.resilience import breakers as _breakers
            checks["circuit_breakers"] = _breakers.states()
        except Exception:
            checks["circuit_breakers"] = "unavailable"

        status_code = 200 if checks["status"] == "healthy" else 503
        return JSONResponse(content=checks, status_code=status_code)


    @app.get("/")
    async def root():
        return {"app": settings.APP_NAME, "status": "running", "docs": "/docs"}

    return app


# Module-level app instance for uvicorn
app = create_app()
