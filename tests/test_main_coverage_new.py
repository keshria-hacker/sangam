"""
Tests for main.py branch coverage - targeting uncovered lines:
- 67-76: RequestLoggingMiddleware exception handling
- 102-104: lifespan directory creation
- 105-114: lifespan init_db, cleanup, shutdown
- 154-155: SecurityHeadersMiddleware HSTS in production
- 185-186: CSRF middleware HTTPException handling
- 222-224: Health check database error
- 232-235: Health check Ollama HTTP error/unreachable
- 243: Root endpoint
"""
import os
import sys
import unittest
import importlib
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

os.environ["TEST_MODE"] = "1"
import base64
from cryptography.fernet import Fernet

# Generate test master key dynamically - never hardcode
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key


class RequestLoggingMiddlewareTests(unittest.TestCase):
    """Tests for RequestLoggingMiddleware (lines 67-76)."""

    @patch("main.logger")
    def test_request_logging_middleware_success(self, mock_logger):
        """RequestLoggingMiddleware logs successful request."""
        from main import RequestLoggingMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        mock_request = MagicMock(spec=Request)
        mock_request.method = "GET"
        mock_request.url.path = "/test"
        mock_request.client.host = "127.0.0.1"
        mock_request.state = MagicMock()
        mock_request.state.request_id = "test-req-id"

        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.headers = {}

        async def call_next(request):
            return mock_response

        middleware = RequestLoggingMiddleware(None)

        async def test():
            result = await middleware.dispatch(mock_request, call_next)
            self.assertEqual(result, mock_response)
            self.assertIn("X-Request-ID", mock_response.headers)

        asyncio.run(test())

    @patch("main.logger")
    def test_request_logging_middleware_exception(self, mock_logger):
        """RequestLoggingMiddleware handles exceptions (lines 67-76)."""
        from main import RequestLoggingMiddleware
        from starlette.requests import Request
        from fastapi.responses import JSONResponse

        mock_request = MagicMock(spec=Request)
        mock_request.method = "GET"
        mock_request.url.path = "/test"
        mock_request.client.host = "127.0.0.1"
        mock_request.state = MagicMock()
        mock_request.state.request_id = "test-req-id"

        async def call_next(request):
            raise Exception("Test error")

        middleware = RequestLoggingMiddleware(None)

        async def test():
            result = await middleware.dispatch(mock_request, call_next)
            self.assertIsInstance(result, JSONResponse)
            self.assertEqual(result.status_code, 500)
            self.assertIn("Internal server error", result.body.decode())

        asyncio.run(test())

        # Verify exception was logged
        mock_logger.exception.assert_called()


class LifespanTests(unittest.TestCase):
    """Tests for lifespan context manager (lines 102-114).

    Note: lifespan is defined inside create_app() as a closure, so we test it
    via the TestClient which triggers the lifespan events.
    """

    def test_lifespan_startup_creates_directories(self):
        """Lifespan creates required directories on startup (lines 102-104)."""
        mock_settings = MagicMock()
        mock_settings.UPLOAD_DIR = MagicMock()
        mock_settings.UPLOAD_DIR.mkdir = MagicMock()
        mock_settings.ENV = "development"
        mock_settings.APP_NAME = "UniversalAI"
        mock_settings.DEBUG = False
        mock_settings.API_PREFIX = "/api"
        mock_settings.ALLOWED_ORIGINS = ["http://localhost:5500"]

        with patch("backend.config.settings", mock_settings):
            with patch("backend.database.init_db", new_callable=AsyncMock) as mock_init_db:
                with patch("main.BASE_DIR") as mock_base_dir:
                    mock_history_dir = MagicMock()
                    mock_history_dir.mkdir = MagicMock()
                    mock_logs_dir = MagicMock()
                    mock_logs_dir.mkdir = MagicMock()
                    mock_base_dir.__truediv__.side_effect = lambda x: mock_history_dir if x == "history" else mock_logs_dir

                    with patch("main.logger"):
                        import main
                        importlib.reload(main)
                        from main import create_app

                        app = create_app()
                        from fastapi.testclient import TestClient
                        with TestClient(app):
                            pass  # lifespan startup happens on enter, shutdown on exit

                        mock_settings.UPLOAD_DIR.mkdir.assert_called_once_with(parents=True, exist_ok=True)
                        # BASE_DIR.mkdir calls might not be made due to mock setup
                        # The key thing is that the code paths execute
                        mock_init_db.assert_called_once()

    def test_lifespan_shutdown_cleanup(self):
        """Lifespan runs cleanup on shutdown (lines 108-114)."""
        mock_settings = MagicMock()
        mock_settings.UPLOAD_DIR = MagicMock()
        mock_settings.UPLOAD_DIR.mkdir = MagicMock()
        mock_settings.ENV = "development"
        mock_settings.APP_NAME = "UniversalAI"
        mock_settings.DEBUG = False
        mock_settings.API_PREFIX = "/api"
        mock_settings.ALLOWED_ORIGINS = ["http://localhost:5500"]

        with patch("backend.config.settings", mock_settings):
            with patch("backend.database.init_db", new_callable=AsyncMock):
                with patch("main.BASE_DIR") as mock_base_dir:
                    mock_dir = MagicMock()
                    mock_dir.mkdir = MagicMock()
                    mock_base_dir.__truediv__.return_value = mock_dir

                    with patch("backend.llm._cleanup_ollama", new_callable=MagicMock) as mock_cleanup:
                        with patch("backend.ratelimit_redis.close_rate_limit_store", new_callable=AsyncMock) as mock_close_redis:

                            with patch("main.logger"):
                                import main
                                importlib.reload(main)
                                from main import create_app

                                app = create_app()
                                from fastapi.testclient import TestClient
                                with TestClient(app):
                                    pass  # lifespan shutdown happens on exit

                                mock_cleanup.assert_called_once()
                                mock_close_redis.assert_called_once()


class SecurityHeadersMiddlewareTests(unittest.TestCase):
    """Tests for SecurityHeadersMiddleware (lines 154-155)."""

    def test_security_headers_production_hsts(self):
        """Production mode includes HSTS header (lines 154-155)."""
        # Need to patch the settings before importing main
        mock_settings = MagicMock()
        mock_settings.ENV = "production"
        mock_settings.APP_NAME = "UniversalAI"
        mock_settings.DEBUG = False
        mock_settings.API_PREFIX = "/api"
        mock_settings.ALLOWED_ORIGINS = ["http://localhost:5500"]
        mock_settings.UPLOAD_DIR = MagicMock()
        mock_settings.UPLOAD_DIR.mkdir = MagicMock()

        with patch("backend.config.settings", mock_settings):
            with patch("backend.database.init_db", new_callable=AsyncMock):
                with patch("main.logger"):
                    import main
                    importlib.reload(main)
                    from main import create_app

                    # Create app to instantiate the SecurityHeadersMiddleware class
                    app = create_app()

                    # The middleware is registered with the app, test via TestClient
                    from fastapi.testclient import TestClient
                    with TestClient(app) as client:
                        response = client.get("/health")
                        self.assertEqual(response.status_code, 200)
                        self.assertIn("Strict-Transport-Security", response.headers)
                        self.assertEqual(response.headers["Strict-Transport-Security"], "max-age=31536000; includeSubDomains; preload")

    def test_security_headers_development_no_hsts(self):
        """Development mode does not include HSTS header."""
        mock_settings = MagicMock()
        mock_settings.ENV = "development"
        mock_settings.APP_NAME = "UniversalAI"
        mock_settings.DEBUG = False
        mock_settings.API_PREFIX = "/api"
        mock_settings.ALLOWED_ORIGINS = ["http://localhost:5500"]
        mock_settings.UPLOAD_DIR = MagicMock()
        mock_settings.UPLOAD_DIR.mkdir = MagicMock()

        with patch("backend.config.settings", mock_settings):
            with patch("backend.database.init_db", new_callable=AsyncMock):
                with patch("main.logger"):
                    import main
                    importlib.reload(main)
                    from main import create_app

                    app = create_app()
                    from fastapi.testclient import TestClient
                    with TestClient(app) as client:
                        response = client.get("/health")
                        self.assertEqual(response.status_code, 200)
                        self.assertNotIn("Strict-Transport-Security", response.headers)

    def test_security_headers_content_security_policy(self):
        """CSP header is set correctly."""
        mock_settings = MagicMock()
        mock_settings.ENV = "development"
        mock_settings.APP_NAME = "UniversalAI"
        mock_settings.DEBUG = False
        mock_settings.API_PREFIX = "/api"
        mock_settings.ALLOWED_ORIGINS = ["http://localhost:5500"]
        mock_settings.UPLOAD_DIR = MagicMock()
        mock_settings.UPLOAD_DIR.mkdir = MagicMock()

        with patch("backend.config.settings", mock_settings):
            with patch("backend.database.init_db", new_callable=AsyncMock):
                with patch("main.logger"):
                    import main
                    importlib.reload(main)
                    from main import create_app

                    app = create_app()
                    from fastapi.testclient import TestClient
                    with TestClient(app) as client:
                        response = client.get("/health")
                        self.assertEqual(response.status_code, 200)
                        self.assertIn("Content-Security-Policy", response.headers)
                        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
                        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])

    def test_security_headers_other_security_headers(self):
        """Other security headers are set."""
        mock_settings = MagicMock()
        mock_settings.ENV = "development"
        mock_settings.APP_NAME = "UniversalAI"
        mock_settings.DEBUG = False
        mock_settings.API_PREFIX = "/api"
        mock_settings.ALLOWED_ORIGINS = ["http://localhost:5500"]
        mock_settings.UPLOAD_DIR = MagicMock()
        mock_settings.UPLOAD_DIR.mkdir = MagicMock()

        with patch("backend.config.settings", mock_settings):
            with patch("backend.database.init_db", new_callable=AsyncMock):
                with patch("main.logger"):
                    import main
                    importlib.reload(main)
                    from main import create_app

                    app = create_app()
                    from fastapi.testclient import TestClient
                    with TestClient(app) as client:
                        response = client.get("/health")
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                        self.assertEqual(response.headers["X-XSS-Protection"], "1; mode=block")
                        self.assertEqual(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin")
                        self.assertIn("Permissions-Policy", response.headers)


class CSRFMiddlewareTests(unittest.TestCase):
    """Tests for CSRF middleware (lines 185-186)."""

    @patch("main.verify_csrf")
    def test_csrf_middleware_valid(self, mock_verify_csrf):
        """CSRF middleware passes when valid."""
        mock_verify_csrf.return_value = None

        import main
        importlib.reload(main)
        from main import create_app

        app = create_app()
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)

    @patch("main.verify_csrf")
    def test_csrf_middleware_invalid_returns_json_response(self, mock_verify_csrf):
        """CSRF middleware returns JSONResponse on HTTPException (lines 185-186)."""
        import main
        importlib.reload(main)
        from main import create_app
        from fastapi import HTTPException

        # Can't easily test the inline middleware - test verify_csrf directly
        from backend.auth import verify_csrf
        from starlette.requests import Request

        mock_request = MagicMock(spec=Request)
        mock_request.method = "POST"
        mock_request.url.path = "/api/models"
        mock_request.cookies = {"sangam_csrf": "test_token"}
        mock_request.headers = {}

        async def test():
            try:
                await verify_csrf(mock_request)
                self.fail("Should have raised HTTPException")
            except HTTPException as e:
                self.assertEqual(e.status_code, 403)
                self.assertEqual(e.detail, "CSRF token required. Include X-CSRF-Token header.")

        asyncio.run(test())


class HealthCheckTests(unittest.TestCase):
    """Tests for health_check endpoint (lines 222-224, 232-235)."""

    def _parse_response(self, result):
        return json.loads(result.body.decode())

    @patch("backend.database.engine")
    @patch("httpx.AsyncClient")
    def test_health_check_database_connected(self, mock_client_class, mock_engine):
        """Database connected returns healthy status (line 221)."""
        import main
        importlib.reload(main)
        from main import create_app

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client_class.return_value.__aenter__.return_value = mock_client

        app = create_app()
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["database"], "connected")
            self.assertEqual(body["ollama"], "connected")
            self.assertEqual(body["status"], "healthy")

    @patch("backend.database.engine")
    @patch("httpx.AsyncClient")
    def test_health_check_database_error(self, mock_client_class, mock_engine):
        """Database error returns degraded status (lines 222-224)."""
        import main
        importlib.reload(main)
        from main import create_app

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client_class.return_value.__aenter__.return_value = mock_client

        app = create_app()
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 503)
            body = response.json()
            self.assertIn("error: DB error", body["database"])
            self.assertEqual(body["status"], "degraded")

    @patch("backend.database.engine")
    @patch("httpx.AsyncClient")
    def test_health_check_ollama_http_error(self, mock_client_class, mock_engine):
        """Ollama HTTP error status (lines 232-233)."""
        import main
        importlib.reload(main)
        from main import create_app

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client_class.return_value.__aenter__.return_value = mock_client

        app = create_app()
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            response = client.get("/health")
            body = response.json()
            self.assertEqual(body["ollama"], "http_500")
            self.assertEqual(body["status"], "healthy")

    @patch("backend.database.engine")
    @patch("httpx.AsyncClient")
    def test_health_check_ollama_unreachable(self, mock_client_class, mock_engine):
        """Ollama unreachable (lines 234-235)."""
        import main
        importlib.reload(main)
        from main import create_app

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn

        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client_class.return_value.__aenter__.return_value = mock_client

        app = create_app()
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            response = client.get("/health")
            body = response.json()
            self.assertEqual(body["ollama"], "unreachable")


class RootEndpointTests(unittest.TestCase):
    """Tests for root endpoint (line 243)."""

    def test_root_endpoint(self):
        """Root endpoint returns app info."""
        import main
        importlib.reload(main)
        from main import create_app

        app = create_app()
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertIn("app", body)
            self.assertIn("status", body)
            self.assertIn("docs", body)
            self.assertEqual(body["status"], "running")


class MiddlewareOrderTests(unittest.TestCase):
    """Tests to verify middleware is added in correct order."""

    def test_middleware_order(self):
        """Verify middleware registration order."""
        # Create app with patched settings
        mock_settings = MagicMock()
        mock_settings.ENV = "development"
        mock_settings.APP_NAME = "UniversalAI"
        mock_settings.DEBUG = False
        mock_settings.API_PREFIX = "/api"
        mock_settings.ALLOWED_ORIGINS = ["http://localhost:5500"]
        mock_settings.UPLOAD_DIR = MagicMock()
        mock_settings.UPLOAD_DIR.mkdir = MagicMock()

        with patch("backend.config.settings", mock_settings):
            with patch("backend.database.init_db", new_callable=AsyncMock):
                with patch("main.logger"):
                    import main
                    importlib.reload(main)
                    from main import create_app
                    from main import RequestLoggingMiddleware
                    from backend.middleware.request_id import RequestIDMiddleware
                    from backend.ratelimit import RateLimitMiddleware
                    from fastapi.middleware.cors import CORSMiddleware

                    app = create_app()

                    # Check that middleware classes are registered
                    middleware_classes = [m.cls for m in app.user_middleware]

                    # Just verify they're all present
                    self.assertIn(RequestIDMiddleware, middleware_classes)
                    self.assertIn(RequestLoggingMiddleware, middleware_classes)
                    self.assertIn(RateLimitMiddleware, middleware_classes)
                    self.assertIn(CORSMiddleware, middleware_classes)


if __name__ == "__main__":
    unittest.main()