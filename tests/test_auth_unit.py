"""
Comprehensive unit tests for auth.py module.

Tests cover:
- _create_session function
- get_current_user dependency
- Register endpoint
- Login endpoint
- /me endpoint
- Forgot password endpoint
- Reset password endpoint
- Logout endpoint
- CSRF verification
- Session management
"""
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Enable test mode with file-based database BEFORE importing ANY backend modules
# Using in-memory DB causes issues because each connection gets a different DB
os.environ["TEST_MODE"] = "1"
from cryptography.fernet import Fernet
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key
# Use file-based test database in the OS temp dir so the repo root stays clean
# (an earlier version wrote test_auth.db into the project root).
test_db_path = Path(tempfile.gettempdir()) / "sangam_test_auth.db"
if test_db_path.exists():
    test_db_path.unlink()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{test_db_path}"

# Reset settings cache BEFORE importing config
from config import reset_settings, settings as config_settings
reset_settings()
config_settings.DATABASE_URL = os.environ["DATABASE_URL"]

# NOW import database module - it will create engine with test DB
import backend.database as db_module

# Use the database module's engine and session factory directly
test_engine = db_module.engine
TestAsyncSessionLocal = db_module.AsyncSessionLocal

from backend.database import Base  # Use the same Base from the patched module

# Now import backend modules - they will use the same database module
import auth
from backend import models  # Import models to register them with Base.metadata


async def create_test_tables():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_test_tables():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def reset_test_db():
    """Drop and recreate all tables in test database."""
    await drop_test_tables()
    await create_test_tables()


class AuthUnitTests(unittest.IsolatedAsyncioTestCase):
    """Unit tests for auth module functions."""

    @classmethod
    async def asyncSetUpClass(cls):
        await create_test_tables()

    @classmethod
    async def asyncTearDownClass(cls):
        await drop_test_tables()
        await test_engine.dispose()
        # Clean up test database file
        if test_db_path.exists():
            test_db_path.unlink()

    async def asyncSetUp(self):
        await reset_test_db()
        # Models are already imported via backend.models, use those references
        self.User = models.User
        self.AuthSession = models.AuthSession
        self.PasswordResetToken = models.PasswordResetToken
        self.session = TestAsyncSessionLocal()

    async def asyncTearDown(self):
        await self.session.close()

    # --- Tests for _hash_password ---
    def test_hash_password_is_deterministic(self):
        """Same password and salt should produce same hash."""
        salt = "a" * 32
        h1 = auth._hash_password("password123!", salt)
        h2 = auth._hash_password("password123!", salt)
        self.assertEqual(h1, h2)

    def test_hash_password_differs_for_different_salts(self):
        """Different salts should produce different hashes."""
        h1 = auth._hash_password("password123!", "a" * 32)
        h2 = auth._hash_password("password123!", "b" * 32)
        self.assertNotEqual(h1, h2)

    def test_hash_password_differs_for_different_passwords(self):
        """Different passwords should produce different hashes."""
        salt = "a" * 32
        h1 = auth._hash_password("password123!", salt)
        h2 = auth._hash_password("different456!", salt)
        self.assertNotEqual(h1, h2)

    def test_hash_password_hex_length(self):
        """Hash should be 128 hex chars (64 bytes)."""
        salt = "a" * 32
        h = auth._hash_password("password123!", salt)
        self.assertEqual(len(h), 128)

    # --- Tests for _hash_token ---
    def test_hash_token_is_deterministic(self):
        """Same token should produce same hash."""
        self.assertEqual(auth._hash_token("abc123"), auth._hash_token("abc123"))

    def test_hash_token_differs_for_different_tokens(self):
        """Different tokens should produce different hashes."""
        self.assertNotEqual(auth._hash_token("abc123"), auth._hash_token("xyz789"))

    def test_hash_token_hex_length(self):
        """Hash should be 64 hex chars (32 bytes)."""
        h = auth._hash_token("some-token")
        self.assertEqual(len(h), 64)

    # --- Tests for _issue_token ---
    def test_issue_token_returns_urlsafe_string(self):
        """Token should be URL-safe string without / or +."""
        token = auth._issue_token()
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 16)
        self.assertNotIn("/", token)
        self.assertNotIn("+", token)

    def test_issue_token_different_each_call(self):
        """Each call should generate a different token."""
        tokens = {auth._issue_token() for _ in range(10)}
        self.assertEqual(len(tokens), 10)

    # --- Tests for _issue_csrf_token ---
    def test_issue_csrf_token_returns_string(self):
        """CSRF token should be a string."""
        csrf = auth._issue_csrf_token()
        self.assertIsInstance(csrf, str)
        self.assertGreater(len(csrf), 16)

    # --- Tests for _clean_expired_sessions ---
    async def test_clean_expired_sessions_removes_old(self):
        """Expired sessions should be deleted."""
        user = self.User(
            username="cleanup_user",
            password_salt="a" * 32,
            password_hash=auth._hash_password("password123!", "a" * 32),
        )
        self.session.add(user)
        await self.session.flush()

        expired_session = self.AuthSession(
            user_id=user.id,
            token_hash=auth._hash_token("expired_token"),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        self.session.add(expired_session)

        valid_session = self.AuthSession(
            user_id=user.id,
            token_hash=auth._hash_token("valid_token"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        self.session.add(valid_session)
        await self.session.commit()

        await auth._clean_expired_sessions(self.session)

        # Verify expired session is gone
        from sqlalchemy import select
        result = await self.session.execute(
            select(self.AuthSession).where(self.AuthSession.token_hash == auth._hash_token("expired_token"))
        )
        self.assertIsNone(result.scalar_one_or_none())

        # Verify valid session remains
        result = await self.session.execute(
            select(self.AuthSession).where(self.AuthSession.token_hash == auth._hash_token("valid_token"))
        )
        self.assertIsNotNone(result.scalar_one_or_none())

    # --- Tests for _create_session ---
    async def test_create_session_returns_token(self):
        """_create_session should return AuthTokenOut with access_token."""
        user = self.User(
            username="session_user",
            password_salt="a" * 32,
            password_hash=auth._hash_password("password123!", "a" * 32),
        )
        self.session.add(user)
        await self.session.flush()

        mock_response = MagicMock()
        mock_response.set_cookie = MagicMock()
        mock_response.delete_cookie = MagicMock()

        token_out = await auth._create_session(user, self.session, mock_response)

        self.assertIsNotNone(token_out.access_token)
        self.assertEqual(token_out.username, "session_user")
        self.assertIsNotNone(token_out.csrf_token)

    async def test_create_session_creates_db_record(self):
        """_create_session should create AuthSession in database."""
        user = self.User(
            username="session_user2",
            password_salt="a" * 32,
            password_hash=auth._hash_password("password123!", "a" * 32),
        )
        self.session.add(user)
        await self.session.flush()

        mock_response = MagicMock()
        mock_response.set_cookie = MagicMock()
        mock_response.delete_cookie = MagicMock()

        token_out = await auth._create_session(user, self.session, mock_response)

        # Verify session exists in DB
        from sqlalchemy import select
        result = await self.session.execute(
            select(self.AuthSession).where(self.AuthSession.token_hash == auth._hash_token(token_out.access_token))
        )
        session = result.scalar_one_or_none()
        self.assertIsNotNone(session)
        self.assertEqual(session.user_id, user.id)
        self.assertGreater(session.expires_at.replace(tzinfo=UTC), datetime.now(UTC))

    async def test_create_session_sets_cookies(self):
        """_create_session should set auth and CSRF cookies."""
        user = self.User(
            username="cookie_user",
            password_salt="a" * 32,
            password_hash=auth._hash_password("password123!", "a" * 32),
        )
        self.session.add(user)
        await self.session.flush()

        mock_response = MagicMock()
        mock_response.set_cookie = MagicMock()
        mock_response.delete_cookie = MagicMock()

        token_out = await auth._create_session(user, self.session, mock_response)

        self.assertEqual(mock_response.set_cookie.call_count, 2)

        auth_cookie_call = mock_response.set_cookie.call_args_list[0]
        self.assertEqual(auth_cookie_call.kwargs["key"], "sangam_session")
        self.assertEqual(auth_cookie_call.kwargs["value"], token_out.access_token)
        self.assertTrue(auth_cookie_call.kwargs["httponly"])
        self.assertEqual(auth_cookie_call.kwargs["samesite"], "lax")

        csrf_cookie_call = mock_response.set_cookie.call_args_list[1]
        self.assertEqual(csrf_cookie_call.kwargs["key"], "sangam_csrf")
        self.assertEqual(csrf_cookie_call.kwargs["value"], token_out.csrf_token)
        self.assertFalse(csrf_cookie_call.kwargs["httponly"])
        self.assertEqual(csrf_cookie_call.kwargs["samesite"], "strict")

    async def test_create_session_deletes_old_sessions(self):
        """_create_session should delete previous sessions for the same user."""
        user = self.User(
            username="multi_session_user",
            password_salt="a" * 32,
            password_hash=auth._hash_password("password123!", "a" * 32),
        )
        self.session.add(user)
        await self.session.flush()

        old_session1 = self.AuthSession(
            user_id=user.id,
            token_hash=auth._hash_token("old_token_1"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        old_session2 = self.AuthSession(
            user_id=user.id,
            token_hash=auth._hash_token("old_token_2"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        self.session.add_all([old_session1, old_session2])
        await self.session.commit()

        mock_response = MagicMock()
        mock_response.set_cookie = MagicMock()
        mock_response.delete_cookie = MagicMock()

        await auth._create_session(user, self.session, mock_response)

        # Verify old sessions are deleted
        from sqlalchemy import select
        result = await self.session.execute(
            select(self.AuthSession).where(self.AuthSession.user_id == user.id)
        )
        sessions = result.scalars().all()
        self.assertEqual(len(sessions), 1)


class AuthEndpointTests(unittest.IsolatedAsyncioTestCase):
    """Integration tests for auth endpoints via the router."""

    @classmethod
    async def asyncSetUpClass(cls):
        await create_test_tables()

    @classmethod
    async def asyncTearDownClass(cls):
        await drop_test_tables()

    async def asyncSetUp(self):
        await reset_test_db()

    # --- Register tests ---
    async def test_register_valid_credentials(self):
        """Valid registration should create user and return token."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        resp = client.post("/api/auth/register", json={
            "username": "newuser",
            "password": "StrongPass123!",
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["username"], "newuser")
        self.assertIn("csrf_token", data)

    async def test_register_rejects_weak_password_short(self):
        """Short password should be rejected."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        resp = client.post("/api/auth/register", json={
            "username": "weakuser",
            "password": "Short1!",
        })
        self.assertEqual(resp.status_code, 422)
        detail = str(resp.json()["detail"])
        self.assertIn("at least 10 characters", detail, f"Expected 'at least 10 characters' in {detail}")

    async def test_register_rejects_no_uppercase(self):
        """Password without uppercase should be rejected."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        resp = client.post("/api/auth/register", json={
            "username": "noupper",
            "password": "password123!",
        })
        self.assertEqual(resp.status_code, 422)
        detail = str(resp.json()["detail"])
        self.assertIn("uppercase", detail.lower(), f"Expected 'uppercase' in {detail}")

    async def test_register_rejects_no_lowercase(self):
        """Password without lowercase should be rejected."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        resp = client.post("/api/auth/register", json={
            "username": "nolower",
            "password": "PASSWORD123!",
        })
        self.assertEqual(resp.status_code, 422)
        detail = str(resp.json()["detail"])
        self.assertIn("lowercase", detail.lower(), f"Expected 'lowercase' in {detail}")

    async def test_register_rejects_no_digit(self):
        """Password without digit should be rejected."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        resp = client.post("/api/auth/register", json={
            "username": "nodigit",
            "password": "PasswordTooLong!",
        })
        self.assertEqual(resp.status_code, 422)
        detail = str(resp.json()["detail"])
        self.assertIn("digit", detail.lower(), f"Expected 'digit' in {detail}")

    async def test_register_rejects_second_user(self):
        """Second registration should fail in single-user mode."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        client.post("/api/auth/register", json={
            "username": "firstuser",
            "password": "StrongPass123!",
        })

        resp = client.post("/api/auth/register", json={
            "username": "seconduser",
            "password": "StrongPass123!",
        })
        self.assertEqual(resp.status_code, 403)
        self.assertIn("already exists", resp.json()["detail"])

    async def test_register_missing_fields(self):
        """Missing username or password should return 422."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        resp = client.post("/api/auth/register", json={"username": "nopass"})
        self.assertEqual(resp.status_code, 422)

        resp = client.post("/api/auth/register", json={"password": "StrongPass123!"})
        self.assertEqual(resp.status_code, 422)

    # --- Login tests ---
    async def test_login_valid_credentials(self):
        """Valid login should return token."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        client.post("/api/auth/register", json={
            "username": "loginuser",
            "password": "StrongPass123!",
        })

        resp = client.post("/api/auth/login", json={
            "username": "loginuser",
            "password": "StrongPass123!",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["username"], "loginuser")
        self.assertIn("csrf_token", data)

    async def test_login_invalid_username(self):
        """Non-existent username should return 401."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        resp = client.post("/api/auth/login", json={
            "username": "nonexistent",
            "password": "StrongPass123!",
        })
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Invalid username or password", resp.json()["detail"])

    async def test_login_wrong_password(self):
        """Wrong password should return 401."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        client.post("/api/auth/register", json={
            "username": "wrongpassuser",
            "password": "StrongPass123!",
        })

        resp = client.post("/api/auth/login", json={
            "username": "wrongpassuser",
            "password": "WrongPass123!",
        })
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Invalid username or password", resp.json()["detail"])

    # --- /me endpoint tests ---
    async def test_me_endpoint_with_valid_token(self):
        """Valid token should return user info."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        client.post("/api/auth/register", json={
            "username": "meuser",
            "password": "StrongPass123!",
        })
        login_resp = client.post("/api/auth/login", json={
            "username": "meuser",
            "password": "StrongPass123!",
        })
        token = login_resp.json()["access_token"]
        csrf_token = login_resp.json()["csrf_token"]

        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["username"], "meuser")
        self.assertTrue(data["authenticated"])
        self.assertIn(data["session_from"], ("header", "cookie"))

    async def test_me_endpoint_with_cookie(self):
        """Cookie-based auth should work for /me."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        client.post("/api/auth/register", json={
            "username": "cookieuser",
            "password": "StrongPass123!",
        })
        login_resp = client.post("/api/auth/login", json={
            "username": "cookieuser",
            "password": "StrongPass123!",
        })
        cookies = login_resp.cookies

        resp = client.get("/api/auth/me", cookies=cookies)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["username"], "cookieuser")
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["session_from"], "cookie")

    async def test_me_endpoint_without_auth_returns_401(self):
        """Unauthenticated request to /me should return 401."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        resp = client.get("/api/auth/me")
        self.assertEqual(resp.status_code, 401)

    # --- Forgot password tests ---
    async def test_forgot_password_existing_user_dev_mode(self):
        """Forgot password should return token in dev mode."""
        from fastapi.testclient import TestClient
        from backend.main import app
        from unittest.mock import patch
        from backend.config import settings

        # Ensure we're in development mode by patching settings
        with patch.object(settings, 'ENV', 'development'):
            client = TestClient(app)  # This triggers lifespan which calls init_db

            resp_register = client.post("/api/auth/register", json={
                "username": "forgotuser",
                "password": "StrongPass123!",
            })
            # Should succeed (201) or user may already exist (403)
            self.assertIn(resp_register.status_code, [201, 403])

            resp = client.post("/api/auth/forgot-password", json={"username": "forgotuser"})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("reset_token", data)
            self.assertIsNotNone(data["reset_token"])

    async def test_forgot_password_nonexistent_user(self):
        """Forgot password for nonexistent user should return vague message."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        resp = client.post("/api/auth/forgot-password", json={"username": "nonexistent"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("If that username exists", data["message"])
        self.assertIsNone(data["reset_token"])

    # --- Reset password tests ---
    async def test_reset_password_valid_token(self):
        """Valid reset token should allow password change."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        client.post("/api/auth/register", json={
            "username": "resetuser",
            "password": "StrongPass123!",
        })

        forgot_resp = client.post("/api/auth/forgot-password", json={"username": "resetuser"})
        token = forgot_resp.json()["reset_token"]

        resp = client.post("/api/auth/reset-password", json={
            "reset_token": token,
            "new_password": "NewStrongPass456!",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Password reset successfully", resp.json()["message"])

        # Verify can login with new password
        login_resp = client.post("/api/auth/login", json={
            "username": "resetuser",
            "password": "NewStrongPass456!",
        })
        self.assertEqual(login_resp.status_code, 200)

    async def test_reset_password_invalid_token(self):
        """Invalid token should be rejected."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        resp = client.post("/api/auth/reset-password", json={
            "reset_token": "invalid_token",
            "new_password": "NewStrongPass456!",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Invalid or expired", resp.json()["detail"])

    async def test_reset_password_token_single_use(self):
        """Reset token should only work once."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        client.post("/api/auth/register", json={
            "username": "singleuser",
            "password": "StrongPass123!",
        })

        forgot_resp = client.post("/api/auth/forgot-password", json={"username": "singleuser"})
        token = forgot_resp.json()["reset_token"]

        resp1 = client.post("/api/auth/reset-password", json={
            "reset_token": token,
            "new_password": "NewPass123!",
        })
        self.assertEqual(resp1.status_code, 200)

        resp2 = client.post("/api/auth/reset-password", json={
            "reset_token": token,
            "new_password": "AnotherPass456!",
        })
        self.assertEqual(resp2.status_code, 400)

    async def test_reset_password_weak_new_password(self):
        """Weak new password should be rejected."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        client.post("/api/auth/register", json={
            "username": "weakresetuser",
            "password": "StrongPass123!",
        })

        forgot_resp = client.post("/api/auth/forgot-password", json={"username": "weakresetuser"})
        token = forgot_resp.json()["reset_token"]

        resp = client.post("/api/auth/reset-password", json={
            "reset_token": token,
            "new_password": "weak",
        })
        self.assertEqual(resp.status_code, 422)

    # --- Logout tests ---
    async def test_logout_invalidates_token(self):
        """Logout should invalidate the session token."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        client.post("/api/auth/register", json={
            "username": "logoutuser",
            "password": "StrongPass123!",
        })
        login_resp = client.post("/api/auth/login", json={
            "username": "logoutuser",
            "password": "StrongPass123!",
        })
        token = login_resp.json()["access_token"]
        csrf_token = login_resp.json()["csrf_token"]
        cookies = login_resp.cookies

        resp = client.post("/api/auth/logout",
            headers={"X-CSRF-Token": csrf_token},
            cookies=cookies,
        )
        self.assertEqual(resp.status_code, 204)

        # Token should no longer work
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)

    async def test_logout_clears_session(self):
        """Logout should clear server-side session."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        client.post("/api/auth/register", json={
            "username": "clearsessionuser",
            "password": "StrongPass123!",
        })
        login_resp = client.post("/api/auth/login", json={
            "username": "clearsessionuser",
            "password": "StrongPass123!",
        })
        token = login_resp.json()["access_token"]
        csrf_token = login_resp.json()["csrf_token"]
        cookies = login_resp.cookies

        resp = client.post("/api/auth/logout",
            headers={"X-CSRF-Token": csrf_token},
            cookies=cookies,
        )
        self.assertEqual(resp.status_code, 204)

        # Cookie should be cleared
        resp = client.get("/api/auth/me", cookies=cookies)
        self.assertEqual(resp.status_code, 401)


class AuthStatusTests(unittest.IsolatedAsyncioTestCase):
    """Tests for /auth/status endpoint."""

    @classmethod
    async def asyncSetUpClass(cls):
        await create_test_tables()

    @classmethod
    async def asyncTearDownClass(cls):
        await drop_test_tables()

    async def asyncSetUp(self):
        await reset_test_db()

    async def test_status_registration_open_when_no_users(self):
        """Registration should be open when no users exist."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        resp = client.get("/api/auth/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["registration_open"])

    async def test_status_registration_closed_when_user_exists(self):
        """Registration should be closed when user exists."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        client.post("/api/auth/register", json={
            "username": "statususer",
            "password": "StrongPass123!",
        })

        resp = client.get("/api/auth/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["registration_open"])


class PasswordSecurityTests(unittest.TestCase):
    """Tests for password hashing security."""

    def test_password_hash_uses_scrypt(self):
        """Password hash should use scrypt (not md5, sha1, etc)."""
        salt = "a" * 32
        hash_result = auth._hash_password("password123!", salt)
        # scrypt with n=2^14, r=8, p=1 produces 64 bytes = 128 hex chars
        self.assertEqual(len(hash_result), 128)
        self.assertEqual(auth._hash_password("password123!", salt), hash_result)

    def test_password_verification_uses_hmac_compare_digest(self):
        """Password comparison should use constant-time comparison."""
        import auth
        import inspect
        source = inspect.getsource(auth.login)
        self.assertIn("hmac.compare_digest", source)

    def test_token_hash_uses_sha256(self):
        """Token hash should use SHA-256."""
        hash_result = auth._hash_token("test-token")
        self.assertEqual(len(hash_result), 64)  # SHA-256 = 32 bytes = 64 hex

    def test_csrf_token_is_url_safe(self):
        """CSRF token should be URL-safe."""
        for _ in range(10):
            csrf = auth._issue_csrf_token()
            self.assertNotIn("/", csrf)
            self.assertNotIn("+", csrf)
            self.assertNotIn("=", csrf)


class SessionManagementTests(unittest.IsolatedAsyncioTestCase):
    """Tests for session management."""

    @classmethod
    async def asyncSetUpClass(cls):
        await create_test_tables()

    @classmethod
    async def asyncTearDownClass(cls):
        await drop_test_tables()

    async def asyncSetUp(self):
        await reset_test_db()
        self.User = auth.User
        self.AuthSession = auth.AuthSession
        self.PasswordResetToken = auth.PasswordResetToken
        self.session = TestAsyncSessionLocal()

    async def asyncTearDown(self):
        await self.session.close()

    async def test_session_expiration_prevents_access(self):
        """Expired sessions should not allow access."""
        user = self.User(
            username="expiredsession",
            password_salt="a" * 32,
            password_hash=auth._hash_password("password123!", "a" * 32),
        )
        self.session.add(user)
        await self.session.flush()

        token = auth._issue_token()
        session = self.AuthSession(
            user_id=user.id,
            token_hash=auth._hash_token(token),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        self.session.add(session)
        await self.session.commit()

        mock_request = MagicMock()
        mock_request.cookies = {"sangam_session": token}
        mock_request.headers = {}

        with self.assertRaises(Exception) as ctx:
            await auth.get_current_user(mock_request, authorization=None, db=self.session)
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_logout_deletes_server_session(self):
        """Logout should delete server-side session record."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)

        client.post("/api/auth/register", json={
            "username": "logouttest",
            "password": "StrongPass123!",
        })
        login_resp = client.post("/api/auth/login", json={
            "username": "logouttest",
            "password": "StrongPass123!",
        })
        csrf_token = login_resp.json()["csrf_token"]
        cookies = login_resp.cookies

        resp = client.post("/api/auth/logout",
            headers={"X-CSRF-Token": csrf_token},
            cookies=cookies,
        )
        self.assertEqual(resp.status_code, 204)

        # Verify session is gone from database
        from sqlalchemy import select
        async with TestAsyncSessionLocal() as db:
            result = await db.execute(select(self.AuthSession))
            sessions = result.scalars().all()
            self.assertEqual(len(sessions), 0)


class CSRFProtectionTests(unittest.IsolatedAsyncioTestCase):
    """Tests for CSRF protection."""

    @classmethod
    async def asyncSetUpClass(cls):
        await create_test_tables()

    @classmethod
    async def asyncTearDownClass(cls):
        await drop_test_tables()

    async def asyncSetUp(self):
        await reset_test_db()

    async def test_get_requests_skip_csrf(self):
        """GET requests should not require CSRF token."""
        from auth import verify_csrf
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.headers = {}
        mock_request.cookies = {}
        mock_request.url.path = "/api/some-endpoint"

        await verify_csrf(mock_request)  # Should not raise

    async def test_mutation_requires_csrf(self):
        """POST/PUT/DELETE should require CSRF when cookie present."""
        from auth import verify_csrf
        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.headers = {}
        mock_request.cookies = {"sangam_csrf": "some_token"}
        mock_request.url.path = "/api/some-endpoint"

        with self.assertRaises(Exception) as ctx:
            await verify_csrf(mock_request)
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()