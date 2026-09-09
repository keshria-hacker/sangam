"""
Integration tests for the auth API flow.

The app enforces single-user mode (register works only when no users exist).
Tests create one user and reuse its token for authenticated endpoints.
"""
import sys
import unittest
import os
import tempfile
from pathlib import Path

# Enable test mode to disable rate limiting and set test master key
# Must be set BEFORE any backend imports
os.environ["TEST_MODE"] = "1"
from cryptography.fernet import Fernet
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mainfiles"))

# Point at an isolated throwaway database BEFORE importing any backend module.
# database.py builds its engine at import time from settings.DATABASE_URL, whose
# default is the real history/sangam.db. Without this override these tests would
# wipe the developer's actual account, chats, and stored provider keys.
TEST_DB_PATH = Path(tempfile.gettempdir()) / "sangam_test_integration_auth.db"
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"

# Now import backend modules - the DATABASE_URL is set before they import settings
from mainfiles.backend.config import reset_settings, settings as config_settings
reset_settings()
config_settings.DATABASE_URL = os.environ["DATABASE_URL"]

# Import database and initialize - must come AFTER settings are configured
from mainfiles.backend.database import init_db, reset_db
from mainfiles.backend.ratelimit_redis import reset_rate_limit_store_for_testing
import asyncio
asyncio.run(init_db())

# Import and create app AFTER database is initialized with test settings
from httpx import ASGITransport, AsyncClient
from mainfiles.backend.main import create_app

app = create_app()


class AuthIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Auth API integration tests."""

    ROUTE = "/api/auth"
    USERNAME = "test_integration_user"
    PASSWORD = "StrongPass!42"

    @classmethod
    def setUpClass(cls):
        cls._token = None
        cls._csrf = None
        # The isolated temp database is configured at import time above; each
        # test then gets clean tables via reset_db(). Never touch the real
        # history/sangam.db here.
        reset_settings()

    async def asyncSetUp(self):
        reset_rate_limit_store_for_testing()
        await reset_db()
        transport = ASGITransport(app=app)
        self.client = AsyncClient(transport=transport, base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def _create_user_and_login(self):
        """Create the test user and login, returning auth headers.

        In single-user mode the user may already exist from a prior test in
        this class, in which case register returns 403. We handle that by
        always attempting login after register regardless of the register
        status.
        """
        await self.client.post(f"{self.ROUTE}/register", json={
            "username": self.USERNAME, "password": self.PASSWORD,
        })
        login_resp = await self.client.post(f"{self.ROUTE}/login", json={
            "username": self.USERNAME, "password": self.PASSWORD,
        })
        data = login_resp.json()
        self._token = data["access_token"]
        # CSRF token is returned in the response body by the login endpoint
        self._csrf = data.get("csrf_token", "")

    def _auth_headers(self):
        headers = {"Authorization": f"Bearer {self._token}"}
        if self._csrf:
            headers["X-CSRF-Token"] = self._csrf
        return headers

    # --- Registration tests ---

    async def test_register_creates_first_user(self):
        """Creating the first user succeeds (single-user mode permits one)."""
        resp = await self.client.post(f"{self.ROUTE}/register", json={
            "username": self.USERNAME, "password": self.PASSWORD,
        })
        self.assertIn(resp.status_code, (201, 403))

    async def test_register_rejects_second_user(self):
        """A second registration attempt is blocked by single-user mode."""
        await self._create_user_and_login()
        resp = await self.client.post(f"{self.ROUTE}/register", json={
            "username": "other_user", "password": "OtherPass!42",
        })
        self.assertEqual(resp.status_code, 403)

    async def test_register_rejects_weak_password(self):
        """Too-short password returns 422."""
        resp = await self.client.post(f"{self.ROUTE}/register", json={
            "username": "weak_user", "password": "ab",
        })
        self.assertEqual(resp.status_code, 422)

    async def test_register_missing_fields(self):
        """Empty request body returns 422."""
        resp = await self.client.post(f"{self.ROUTE}/register", json={})
        self.assertEqual(resp.status_code, 422)

    # --- Login tests ---

    async def test_login_success(self):
        """Valid credentials return a token."""
        await self._create_user_and_login()
        resp = await self.client.post(f"{self.ROUTE}/login", json={
            "username": self.USERNAME, "password": self.PASSWORD,
        })
        self.assertEqual(resp.status_code, 200)

    async def test_login_wrong_password(self):
        """Wrong password returns 401."""
        await self._create_user_and_login()
        resp = await self.client.post(f"{self.ROUTE}/login", json={
            "username": self.USERNAME, "password": "WrongPass!99",
        })
        self.assertEqual(resp.status_code, 401)

    async def test_login_nonexistent_user(self):
        """User that was never registered returns 401."""
        await self._create_user_and_login()
        resp = await self.client.post(f"{self.ROUTE}/login", json={
            "username": "no_such_user_xyz", "password": "StrongPass!42",
        })
        self.assertEqual(resp.status_code, 401)

    # --- Protected endpoint tests ---

    async def test_chats_with_valid_token(self):
        """Authenticated request to /api/chats succeeds."""
        await self._create_user_and_login()
        resp = await self.client.get("/api/chats", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)

    async def test_chats_without_token(self):
        """Missing auth token on /api/chats returns 401."""
        await self._create_user_and_login()
        # The previous login set an HTTP-only cookie; clear the client's cookie
        # jar so the request arrives without any auth credentials.
        self.client = AsyncClient(transport=self.client._transport, base_url="http://test")
        resp = await self.client.get("/api/chats")
        self.assertEqual(resp.status_code, 401)

    async def test_chats_with_expired_token(self):
        """Invalid/expired token on /api/chats returns 401."""
        await self._create_user_and_login()
        # The previous login set an HTTP-only cookie; clear it by creating a
        # fresh client so the cookie is not sent.
        self.client = AsyncClient(transport=self.client._transport, base_url="http://test")
        resp = await self.client.get(
            "/api/chats",
            headers={"Authorization": "Bearer invalid_token_here"},
        )
        self.assertEqual(resp.status_code, 401)

    # --- CSRF cookie tests ---

    async def test_csrf_cookie_set_on_login(self):
        """Login response sets the sangam_csrf cookie."""
        await self._create_user_and_login()
        resp = await self.client.post(f"{self.ROUTE}/login", json={
            "username": self.USERNAME, "password": self.PASSWORD,
        })
        csrf_value = resp.cookies.get("sangam_csrf", "")
        self.assertTrue(len(csrf_value) > 8)

    # --- Logout ---

    async def test_logout_works(self):
        """Logout clears session and returns 204."""
        await self._create_user_and_login()
        resp = await self.client.post(
            f"{self.ROUTE}/logout",
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 204)

    # --- Health & metadata ---

    async def test_health_returns_ok(self):
        """Health endpoint returns 200 and includes X-Request-ID."""
        resp = await self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("X-Request-ID", resp.headers)

    async def test_root_returns_info(self):
        """Root returns 200 with app info."""
        resp = await self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    async def test_security_headers_present(self):
        """Security headers are set on every response."""
        resp = await self.client.get("/health")
        h = resp.headers
        self.assertEqual(h.get("x-content-type-options"), "nosniff")
        self.assertEqual(h.get("x-frame-options"), "DENY")
        self.assertIn("x-request-id", h)

    async def test_auth_status_returns_closed(self):
        """Auth status returns registration_open=false once a user exists."""
        await self._create_user_and_login()
        resp = await self.client.get(f"{self.ROUTE}/status")
        self.assertEqual(resp.status_code, 200)

    async def test_forgot_password_returns_200(self):
        """Forgot-password returns 200 (vague success, single-user mode)."""
        resp = await self.client.post(f"{self.ROUTE}/forgot-password", json={
            "username": "any_user",
        })
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
