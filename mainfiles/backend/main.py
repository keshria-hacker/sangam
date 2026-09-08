"""
main.py — application entrypoint. Run with:
    uvicorn main:app --reload --port 8001
"""
import sys
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager

from backend.api import public_router
from backend.api import router as api_router
from backend.auth import get_current_user, verify_csrf
from backend.auth import router as auth_router
from backend.database import init_db
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# --- Structured Logging (loguru) ---
from loguru import logger
from backend.middleware.request_id import RequestIDMiddleware
from backend.ratelimit import RateLimitMiddleware
from backend.skills.api_skills import router as skills_router
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config import BASE_DIR, settings

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
        logger.info("Application startup complete")
        yield
        # Cleanup auto-started Ollama process (if any)
        from backend.llm import _cleanup_ollama
        _cleanup_ollama()
        # Close the rate-limit store (Redis connection, if any)
        from backend.ratelimit_redis import close_rate_limit_store
        await close_rate_limit_store()
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

    # --- Enhanced Health Endpoint ---
    @app.get("/health")
    async def health_check():
        """Comprehensive health check with dependency status."""
        import httpx
        from backend.database import engine
        from sqlalchemy import text

        checks = {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": "1.1.0",
            "database": "unknown",
            "ollama": "unknown",
        }

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

        status_code = 200 if checks["status"] == "healthy" else 503
        return JSONResponse(content=checks, status_code=status_code)


    @app.get("/")
    async def root():
        return {"app": settings.APP_NAME, "status": "running", "docs": "/docs"}

    return app


# Module-level app instance for uvicorn
app = create_app()
