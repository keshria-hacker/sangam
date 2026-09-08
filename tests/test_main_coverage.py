"""
Tests for main.py branch coverage - targeting uncovered lines.
"""
import os
import sys
import unittest
import json
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

os.environ["TEST_MODE"] = "1"
import base64
from cryptography.fernet import Fernet

# Generate test master key dynamically - never hardcode
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key

import importlib

from fastapi.testclient import TestClient


class LifespanTests(unittest.TestCase):
    """Tests for lifespan manager (lines 100-114)."""

    def test_lifespan_startup(self):
        """Test lifespan startup sequence (lines 101-106)."""
        # init_db is imported into main's namespace: from backend.database import init_db
        # Patch at the source to ensure lifespan captures it
        with patch("backend.database.init_db", new_callable=AsyncMock) as mock_init_db:
            with patch("main.logger"):
                # Also need to patch main.settings since SecurityHeadersMiddleware captures it
                with patch("main.settings") as mock_settings:
                    # Use a real Path for UPLOAD_DIR but mock mkdir
                    mock_settings.UPLOAD_DIR = MagicMock()
                    mock_settings.UPLOAD_DIR.mkdir = MagicMock()
                    mock_settings.ENV = "development"  # ensure no HSTS
                    mock_settings.APP_NAME = "UniversalAI"
                    mock_settings.DEBUG = False
                    mock_settings.API_PREFIX = "/api"
                    mock_settings.ALLOWED_ORIGINS = ["http://localhost:5500"]

                    import main
                    importlib.reload(main)
                    from main import create_app

                    app = create_app()
                    # Use context manager to trigger lifespan
                    with TestClient(app) as client:
                        response = client.get("/health")
                        self.assertEqual(response.status_code, 200)

                    # Verify init_db was called during startup
                    mock_init_db.assert_called_once()

    def test_lifespan_shutdown(self):
        """Test lifespan shutdown sequence (lines 108-114)."""
        # The imports inside lifespan are from backend.llm and backend.ratelimit_redis
        # Patch those modules BEFORE importing main
        mock_cleanup_ollama = MagicMock()
        mock_close_redis = AsyncMock()

        with patch("backend.llm._cleanup_ollama", mock_cleanup_ollama):
            with patch("backend.ratelimit_redis.close_rate_limit_store", mock_close_redis):
                with patch("backend.database.init_db", new_callable=AsyncMock):
                    with patch("main.logger"):
                        with patch("main.settings") as mock_settings:
                            mock_settings.UPLOAD_DIR = MagicMock()
                            mock_settings.UPLOAD_DIR.mkdir = MagicMock()
                            mock_settings.ENV = "development"
                            mock_settings.APP_NAME = "UniversalAI"
                            mock_settings.DEBUG = False
                            mock_settings.API_PREFIX = "/api"
                            mock_settings.ALLOWED_ORIGINS = ["http://localhost:5500"]

                            import main
                            importlib.reload(main)
                            from main import create_app

                            app = create_app()
                            # Use context manager to trigger lifespan startup AND shutdown
                            with TestClient(app) as client:
                                response = client.get("/health")
                                self.assertEqual(response.status_code, 200)
                            # Lifespan shutdown happens when context exits

                            # Check if cleanup was called during shutdown
                            mock_cleanup_ollama.assert_called_once()
                            mock_close_redis.assert_called_once()


class HealthCheckTests(unittest.TestCase):
    """Tests for enhanced health check endpoint (lines 202-238)."""

    def _parse_response_body(self, result):
        """Parse JSONResponse body from bytes to dict."""
        return json.loads(result.body.decode())

    @patch("backend.database.engine")
    @patch("httpx.AsyncClient")
    def test_health_check_database_connected(self, mock_client_class, mock_engine):
        """Test health check with database connected (lines 218-221)."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_resp
        mock_client_class.return_value.__aenter__.return_value = mock_client_instance

        import main
        importlib.reload(main)
        from main import create_app

        app = create_app()
        with TestClient(app) as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body.get("database"), "connected")

    @patch("backend.database.engine")
    def test_health_check_database_error(self, mock_engine):
        """Test health check with database error (lines 222-224)."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("DB connection failed"))
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_resp
            mock_client_class.return_value.__aenter__.return_value = mock_client_instance

            import main
            importlib.reload(main)
            from main import create_app

            app = create_app()
            with TestClient(app) as client:
                response = client.get("/health")
                self.assertEqual(response.status_code, 503)
                body = response.json()
                self.assertIn("error:", body.get("database"))

    @patch("backend.database.engine")
    def test_health_check_ollama_connected(self, mock_engine):
        """Test health check with Ollama connected (lines 227-231)."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_resp
            mock_client_class.return_value.__aenter__.return_value = mock_client_instance

            import main
            importlib.reload(main)
            from main import create_app

            app = create_app()
            with TestClient(app) as client:
                response = client.get("/health")
                body = response.json()
                self.assertEqual(body.get("ollama"), "connected")

    @patch("backend.database.engine")
    def test_health_check_ollama_http_error(self, mock_engine):
        """Test health check with Ollama HTTP error (lines 232-233)."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_resp
            mock_client_class.return_value.__aenter__.return_value = mock_client_instance

            import main
            importlib.reload(main)
            from main import create_app

            app = create_app()
            with TestClient(app) as client:
                response = client.get("/health")
                body = response.json()
                self.assertEqual(body.get("ollama"), "http_500")

    @patch("backend.database.engine")
    def test_health_check_ollama_unreachable(self, mock_engine):
        """Test health check with Ollama unreachable (lines 234-235)."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_instance = AsyncMock()
            mock_client_instance.get.side_effect = Exception("Connection refused")
            mock_client_class.return_value.__aenter__.return_value = mock_client_instance

            import main
            importlib.reload(main)
            from main import create_app

            app = create_app()
            with TestClient(app) as client:
                response = client.get("/health")
                body = response.json()
                self.assertEqual(body.get("ollama"), "unreachable")


class SecurityHeadersTests(unittest.TestCase):
    """Tests for security headers middleware (lines 124-157)."""

    def test_security_headers_production_includes_hsts(self):
        """Test security headers in production includes HSTS (lines 154-155)."""
        # The SecurityHeadersMiddleware is defined inside create_app() and captures
        # the `settings` from main's module scope (from backend.config import settings)
        # We need to patch the module-level settings object BEFORE importing main
        mock_settings = MagicMock()
        mock_settings.ENV = "production"
        mock_settings.APP_NAME = "UniversalAI"
        mock_settings.DEBUG = False
        mock_settings.API_PREFIX = "/api"
        mock_settings.ALLOWED_ORIGINS = ["http://localhost:5500"]
        mock_settings.UPLOAD_DIR = MagicMock()
        mock_settings.UPLOAD_DIR.mkdir = MagicMock()

        # Patch backend.config.settings (the module-level instance)
        with patch("backend.config.settings", mock_settings):
            with patch("backend.database.init_db", new_callable=AsyncMock):
                with patch("main.logger"):
                    import main
                    importlib.reload(main)
                    from main import create_app

                    app = create_app()
                    with TestClient(app) as client:
                        response = client.get("/health")
                        self.assertEqual(response.status_code, 200)
                        self.assertIn("Strict-Transport-Security", response.headers)
                        self.assertEqual(response.headers["Strict-Transport-Security"], "max-age=31536000; includeSubDomains; preload")

    def test_security_headers_development_no_hsts(self):
        """Test security headers in development does NOT include HSTS."""
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
                    with TestClient(app) as client:
                        response = client.get("/health")
                        self.assertEqual(response.status_code, 200)
                        self.assertNotIn("Strict-Transport-Security", response.headers)

    def test_security_headers_other_security_headers(self):
        """Test other security headers are always present."""
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
                    with TestClient(app) as client:
                        response = client.get("/health")
                        self.assertEqual(response.status_code, 200)
                        # Check CSP
                        self.assertIn("Content-Security-Policy", response.headers)
                        # Check other headers
                        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                        self.assertEqual(response.headers["X-XSS-Protection"], "1; mode=block")
                        self.assertEqual(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin")
                        self.assertIn("Permissions-Policy", response.headers)


class CSRFMiddlewareTests(unittest.TestCase):
    """Tests for CSRF middleware (lines 181-190)."""

    @patch("main.verify_csrf")
    def test_csrf_middleware_valid(self, mock_verify_csrf):
        """Test CSRF middleware passes when valid."""
        mock_verify_csrf.return_value = None

        import main
        importlib.reload(main)
        from main import create_app

        app = create_app()
        with TestClient(app) as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)

    def test_csrf_middleware_invalid(self):
        """Test CSRF middleware returns JSONResponse on failure (lines 186-189)."""
        # Test verify_csrf function directly since it's imported from backend.auth
        from fastapi import HTTPException

        import main
        importlib.reload(main)

        # Test verify_csrf function directly
        from backend.auth import verify_csrf
        from starlette.requests import Request

        mock_request = MagicMock(spec=Request)

        # Test 1: GET request should pass (skip CSRF)
        mock_request.method = "GET"
        mock_request.url.path = "/api/test"
        mock_request.cookies = {}

        async def test_get():
            await verify_csrf(mock_request)
        asyncio.run(test_get())

        # Test 2: POST to CSRF_SKIP_PATHS should pass
        mock_request.method = "POST"
        mock_request.url.path = "/api/auth/login"  # in CSRF_SKIP_PATHS

        async def test_post_skip():
            await verify_csrf(mock_request)
        asyncio.run(test_post_skip())

        # Test 3: POST to non-skip path without cookie should pass (no session = no CSRF risk)
        mock_request.method = "POST"
        mock_request.url.path = "/api/models"
        mock_request.cookies = {}

        async def test_post_no_cookie():
            await verify_csrf(mock_request)
        asyncio.run(test_post_no_cookie())

        # Test 4: POST with cookie but no header should raise 403
        mock_request.method = "POST"
        mock_request.url.path = "/api/models"
        mock_request.cookies = {"sangam_csrf": "test_token"}
        mock_request.headers = {}

        async def test_post_cookie_no_header():
            try:
                await verify_csrf(mock_request)
                self.fail("Should have raised HTTPException")
            except HTTPException as e:
                self.assertEqual(e.status_code, 403)
                self.assertEqual(e.detail, "CSRF token required. Include X-CSRF-Token header.")
        asyncio.run(test_post_cookie_no_header())

        # Test 5: POST with cookie and mismatched header should raise 403
        mock_request.headers = {"X-CSRF-Token": "wrong_token"}

        async def test_post_mismatched():
            try:
                await verify_csrf(mock_request)
                self.fail("Should have raised HTTPException")
            except HTTPException as e:
                self.assertEqual(e.status_code, 403)
                self.assertEqual(e.detail, "Invalid CSRF token")
        asyncio.run(test_post_mismatched())

        # Test 6: POST with cookie and matching header should pass
        mock_request.headers = {"X-CSRF-Token": "test_token"}

        async def test_post_matched():
            await verify_csrf(mock_request)
        asyncio.run(test_post_matched())


class RootEndpointTests(unittest.TestCase):
    """Tests for root endpoint (lines 241-243)."""

    def test_root_endpoint(self):
        """Test root endpoint returns basic info."""
        import main
        importlib.reload(main)
        from main import create_app

        app = create_app()
        with TestClient(app) as client:
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertIn("app", body)
            self.assertIn("status", body)
            self.assertIn("docs", body)
            self.assertEqual(body["status"], "running")


if __name__ == "__main__":
    unittest.main()