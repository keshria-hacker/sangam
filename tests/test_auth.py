"""test_auth — consolidated tests.

Merged from:
- test_auth.py
- test_auth_unit.py
- test_auth_lockout.py
- test_auth_coverage.py
"""

import os
import sys
from pathlib import Path

# --- Test environment (must run before backend imports) ---------------------
ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "mainfiles")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ["TEST_MODE"] = "1"

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("MASTER_KEY", Fernet.generate_key().decode())

# --- imports ---
import asyncio

import sys

import unittest

from pathlib import Path

from unittest.mock import AsyncMock, MagicMock, patch

from backend.auth import _hash_password, _hash_token, _issue_token

import os

import tempfile

from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet

from backend.config import reset_settings, settings as config_settings

import backend.database as db_module

from backend.database import Base  # Use the same Base from the patched module

import backend.auth as auth

from backend import models  # Import models to register them with Base.metadata

from backend.auth import MAX_LOGIN_ATTEMPTS, login  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from backend.ratelimit_redis import MemoryStore, reset_rate_limit_store_for_testing  # noqa: E402

from backend.schemas import AuthCredentialsIn  # noqa: E402

from backend.auth import _hash_token

from backend.schemas import AuthCredentialsIn, ForgotPasswordIn, ResetPasswordIn


# --- tests ---

class AuthHashTests(unittest.TestCase):
    def test_hash_password_is_deterministic(self):
        salt = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        h1 = _hash_password("correct-horse-battery-staple", salt)
        h2 = _hash_password("correct-horse-battery-staple", salt)
        self.assertEqual(h1, h2)

    def test_hash_password_differs_for_different_salts(self):
        h1 = _hash_password("password123!", "a" * 32)
        h2 = _hash_password("password123!", "b" * 32)
        self.assertNotEqual(h1, h2)

    def test_hash_token_is_deterministic(self):
        self.assertEqual(_hash_token("abc123"), _hash_token("abc123"))

    def test_hash_token_differs_for_different_tokens(self):
        self.assertNotEqual(_hash_token("abc123"), _hash_token("xyz789"))

    def test_issue_token_returns_urlsafe_string(self):
        token = _issue_token()
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 16)
        # No padding or special chars that would break HTTP headers
        self.assertNotIn("/", token)
        self.assertNotIn("+", token)


class AuthValidationTests(unittest.TestCase):
    def test_password_hash_hex_length(self):
        salt = "a" * 32
        h = _hash_password("test-password", salt)
        # scrypt with n=2**14, r=8, p=1 produces 64-byte output = 128 hex chars
        self.assertEqual(len(h), 128)

    def test_token_hash_hex_length(self):
        h = _hash_token("some-random-token")
        # sha256 produces 32 bytes = 64 hex chars
        self.assertEqual(len(h), 64)

    def test_issue_token_length(self):
        token = _issue_token()
        # token_urlsafe(32) = 43 chars typically
        self.assertGreaterEqual(len(token), 40)


if __name__ == "__main__":
    unittest.main()


_test_key = Fernet.generate_key().decode()


test_db_path = Path(tempfile.gettempdir()) / "sangam_test_auth.db"


if test_db_path.exists():
    test_db_path.unlink()


reset_settings()


test_engine = db_module.engine


TestAsyncSessionLocal = db_module.AsyncSessionLocal


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
        import backend.auth as auth
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
        from backend.auth import verify_csrf
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.headers = {}
        mock_request.cookies = {}
        mock_request.url.path = "/api/some-endpoint"

        await verify_csrf(mock_request)  # Should not raise

    async def test_mutation_requires_csrf(self):
        """POST/PUT/DELETE should require CSRF when cookie present."""
        from backend.auth import verify_csrf
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


_test_key = Fernet.generate_key().decode()


def _make_mock_db(scalar_returns):
    """Create a mock db session whose ``scalar`` returns are consumed in order."""
    mock_db = AsyncMock()
    mock_db.scalar.side_effect = scalar_returns
    mock_db.commit = AsyncMock()

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result = MagicMock()
    mock_result.scalars = MagicMock(return_value=mock_scalars)
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.delete = AsyncMock()
    return mock_db


def _make_mock_response():
    """Create a mock Response object."""
    mock_resp = MagicMock()
    mock_resp.set_cookie = MagicMock()
    mock_resp.delete_cookie = MagicMock()
    return mock_resp


class LoginLockoutTests(unittest.TestCase):
    """Lockout behavior of auth.login (audit C-007)."""

    def setUp(self):
        # Give login its own isolated store (not the shared singleton).
        reset_rate_limit_store_for_testing()
        self.store = MemoryStore()
        self._patcher = patch("backend.auth.get_rate_limit_store", return_value=self.store)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _call_login(self, username, password, mock_db, mock_resp):
        """Drive auth.login directly; returns the HTTPException or None."""
        credentials = AuthCredentialsIn(username=username, password=password)

        async def run():
            try:
                await login(credentials, mock_resp, mock_db)
            except HTTPException as exc:
                return exc
            return None

        return asyncio.run(run())

    def test_five_failed_logins_then_lockout(self):
        """Attempts 1-5 return 401; the 6th is blocked with 429."""
        for _ in range(MAX_LOGIN_ATTEMPTS):
            exc = self._call_login(
                "alice", "WrongPassword123", _make_mock_db([None]), _make_mock_response()
            )
            self.assertEqual(exc.status_code, 401)

        exc = self._call_login(
            "alice", "WrongPassword123", _make_mock_db([None]), _make_mock_response()
        )
        self.assertEqual(exc.status_code, 429)
        self.assertIn("Too many failed login attempts", exc.detail)

    def test_successful_login_resets_failure_count(self):
        """A correct login clears the counter; a fresh budget applies again."""
        # 3 failed attempts accumulate (under the limit).
        for _ in range(3):
            exc = self._call_login(
                "alice", "WrongPassword123", _make_mock_db([None]), _make_mock_response()
            )
            self.assertEqual(exc.status_code, 401)

        # Attempt 4 succeeds with the right password and resets the counter.
        user = MagicMock(
            username="alice",
            password_salt="abcdef1234567890",
            password_hash="hash123",
        )
        session = MagicMock()
        with (
            patch("backend.auth._hash_password", return_value="hash123"),
            patch("backend.auth._create_session", new=AsyncMock(return_value=session)) as mock_create,
        ):
            exc = self._call_login(
                "alice", "CorrectPassword123", _make_mock_db([user]), _make_mock_response()
            )
        self.assertIsNone(exc)  # login succeeded
        mock_create.assert_awaited_once()

        # Counter was reset: a fresh budget of 5 applies again.
        for _ in range(MAX_LOGIN_ATTEMPTS):
            exc = self._call_login(
                "alice", "WrongPassword123", _make_mock_db([None]), _make_mock_response()
            )
            self.assertEqual(exc.status_code, 401)
        exc = self._call_login(
            "alice", "WrongPassword123", _make_mock_db([None]), _make_mock_response()
        )
        self.assertEqual(exc.status_code, 429)

    def test_lockout_logs_warning(self):
        """A blocked attempt logs a warning with the username."""
        for _ in range(MAX_LOGIN_ATTEMPTS):
            self._call_login(
                "bob", "WrongPassword123", _make_mock_db([None]), _make_mock_response()
            )

        with patch("backend.auth.logger.warning") as mock_warn:
            exc = self._call_login(
                "bob", "WrongPassword123", _make_mock_db([None]), _make_mock_response()
            )

        self.assertEqual(exc.status_code, 429)
        mock_warn.assert_called_once()
        self.assertIn("Login lockout", mock_warn.call_args.args[0])
        self.assertEqual(mock_warn.call_args.kwargs["username"], "bob")

    def test_lockout_per_username_is_independent(self):
        """One user's failures do not affect another user's budget."""
        # Lock carol out.
        for _ in range(MAX_LOGIN_ATTEMPTS):
            self._call_login(
                "carol", "WrongPassword123", _make_mock_db([None]), _make_mock_response()
            )
        exc = self._call_login(
            "carol", "WrongPassword123", _make_mock_db([None]), _make_mock_response()
        )
        self.assertEqual(exc.status_code, 429)

        # Dave starts with a fresh budget.
        exc = self._call_login(
            "dave", "WrongPassword123", _make_mock_db([None]), _make_mock_response()
        )
        self.assertEqual(exc.status_code, 401)


if __name__ == "__main__":
    unittest.main()


_test_key = Fernet.generate_key().decode()


def _make_mock_dbCoverage(scalar_returns, execute_returns=None):
    """Create a mock db session with specified scalar return values."""
    mock_db = AsyncMock()
    mock_db.scalar.side_effect = scalar_returns
    mock_db.commit = AsyncMock()

    if execute_returns is not None:
        mock_execute = AsyncMock()
        mock_execute.return_value = execute_returns
        mock_db.execute = mock_execute
    else:
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db.execute = AsyncMock(return_value=mock_result)

    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock()
    mock_db.delete = AsyncMock()
    return mock_db


def _make_mock_response():
    """Create a mock Response object."""
    mock_resp = MagicMock()
    mock_resp.set_cookie = MagicMock()
    mock_resp.delete_cookie = MagicMock()
    return mock_resp


class RegisterPasswordValidationTests(unittest.TestCase):
    """Tests for password validation in register endpoint (lines 197, 199, 201)."""

    def test_register_password_no_uppercase(self):
        """Registration fails with password missing uppercase (line 197)."""
        import asyncio
        from backend.auth import register
        from fastapi import HTTPException

        mock_db = _make_mock_dbCoverage([0, None])  # user count = 0, _clean_expired_sessions = None
        mock_resp = _make_mock_response()

        # Use valid length password but missing uppercase - schema allows it
        credentials = AuthCredentialsIn(username="testuser", password="nouppercase123")

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await register(credentials, mock_resp, mock_db)
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("uppercase", ctx.exception.detail)

        asyncio.run(test())

    def test_register_password_no_lowercase(self):
        """Registration fails with password missing lowercase (line 199)."""
        import asyncio
        from backend.auth import register
        from fastapi import HTTPException

        mock_db = _make_mock_dbCoverage([0, None])
        mock_resp = _make_mock_response()

        credentials = AuthCredentialsIn(username="testuser", password="NOLOWERCASE123")

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await register(credentials, mock_resp, mock_db)
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("lowercase", ctx.exception.detail)

        asyncio.run(test())

    def test_register_password_no_digit(self):
        """Registration fails with password missing digit (line 201)."""
        import asyncio
        from backend.auth import register
        from fastapi import HTTPException

        mock_db = _make_mock_dbCoverage([0, None])
        mock_resp = _make_mock_response()

        credentials = AuthCredentialsIn(username="testuser", password="NoDigitsHere")

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await register(credentials, mock_resp, mock_db)
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("digit", ctx.exception.detail)

        asyncio.run(test())


class LoginInvalidCredentialsTests(unittest.TestCase):
    """Tests for login with invalid credentials (line 222)."""

    def test_login_invalid_credentials(self):
        """Login fails with invalid credentials (line 222)."""
        import asyncio
        from backend.auth import login
        from fastapi import HTTPException

        # mock_db.scalar returns user (None = not found)
        mock_db = _make_mock_dbCoverage([None])
        mock_resp = _make_mock_response()

        credentials = AuthCredentialsIn(username="nonexistent", password="WrongPassword123")

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await login(credentials, mock_resp, mock_db)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Invalid username or password", ctx.exception.detail)

        asyncio.run(test())


class ForgotPasswordTests(unittest.TestCase):
    """Tests for forgot password endpoint."""

    def test_forgot_password_user_not_found(self):
        """Forgot password returns vague message for non-existent user (line 253)."""
        import asyncio
        from backend.auth import forgot_password

        mock_db = _make_mock_dbCoverage([None])  # user not found

        payload = ForgotPasswordIn(username="nonexistent")

        async def test():
            result = await forgot_password(payload, mock_db)
            self.assertIn("If that username exists", result.message)
            self.assertIsNone(result.reset_token)

        asyncio.run(test())


class ResetPasswordValidationTests(unittest.TestCase):
    """Tests for password validation in reset_password endpoint (lines 311, 313, 315)."""

    def test_reset_password_no_uppercase(self):
        """Reset password fails without uppercase (line 311)."""
        import asyncio
        from backend.auth import reset_password
        from fastapi import HTTPException

        mock_token = MagicMock(user_id=1, used=False, expires_at=datetime.now(UTC) + timedelta(hours=1))
        mock_db = _make_mock_dbCoverage([mock_token])

        payload = ResetPasswordIn(reset_token="valid_token", new_password="nouppercase123")

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await reset_password(payload, mock_db)
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("uppercase", ctx.exception.detail)

        asyncio.run(test())

    def test_reset_password_no_lowercase(self):
        """Reset password fails without lowercase (line 313)."""
        import asyncio
        from backend.auth import reset_password
        from fastapi import HTTPException

        mock_token = MagicMock(user_id=1, used=False, expires_at=datetime.now(UTC) + timedelta(hours=1))
        mock_db = _make_mock_dbCoverage([mock_token])

        payload = ResetPasswordIn(reset_token="valid_token", new_password="NOLOWERCASE123")

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await reset_password(payload, mock_db)
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("lowercase", ctx.exception.detail)

        asyncio.run(test())

    def test_reset_password_no_digit(self):
        """Reset password fails without digit (line 315)."""
        import asyncio
        from backend.auth import reset_password
        from fastapi import HTTPException

        mock_token = MagicMock(user_id=1, used=False, expires_at=datetime.now(UTC) + timedelta(hours=1))
        mock_db = _make_mock_dbCoverage([mock_token])

        payload = ResetPasswordIn(reset_token="valid_token", new_password="NoDigitsHere")

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await reset_password(payload, mock_db)
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("digit", ctx.exception.detail)

        asyncio.run(test())


class ProductionModeTests(unittest.TestCase):
    """Tests for production mode logging in forgot password (lines 282-288)."""

    @patch("backend.auth.logger.warning")
    @patch("backend.auth.settings")  # Patch the settings object used by auth module
    def test_forgot_password_production_mode_logs_token(self, mock_settings, mock_logger):
        """In production mode, token is logged not returned (lines 282-288)."""
        import asyncio
        from backend.auth import forgot_password
        from backend.schemas import ForgotPasswordIn

        mock_settings.ENV = "production"

        mock_user = MagicMock(id=1, username="testuser_prod")

        # Need to mock db.execute to return result with scalars().all()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=mock_scalars)

        mock_db = _make_mock_dbCoverage([mock_user, None, None], execute_returns=mock_result)
        # Replace the execute mock since we need a custom one
        mock_db.execute = AsyncMock(return_value=mock_result)

        payload = ForgotPasswordIn(username="testuser_prod")

        async def test():
            result = await forgot_password(payload, mock_db)
            self.assertIsNone(result.reset_token)
            self.assertIn("server console/logs", result.message)

            mock_logger.assert_called_once()
            call_args = mock_logger.call_args
            self.assertIn("Password reset requested", call_args[0][0])
            self.assertIn("testuser_prod", call_args[1]["username"])

        asyncio.run(test())


class GetCurrentUserTests(unittest.TestCase):
    """Tests for get_current_user function (lines 190, 195, 203-213)."""

    def test_get_current_user_no_token(self):
        """No token raises 401 (line 165-166)."""
        import asyncio
        from backend.auth import get_current_user
        from fastapi import HTTPException

        mock_request = MagicMock()
        mock_request.cookies.get.return_value = None

        mock_db = AsyncMock()

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await get_current_user(mock_request, authorization=None, db=mock_db)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Sign in is required", ctx.exception.detail)

        asyncio.run(test())

    def test_get_current_user_invalid_token(self):
        """Invalid token raises 401 (lines 175-176)."""
        import asyncio
        from backend.auth import get_current_user
        from fastapi import HTTPException

        mock_request = MagicMock()
        mock_request.cookies.get.return_value = "invalid_token"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await get_current_user(mock_request, authorization=None, db=mock_db)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("session has expired", ctx.exception.detail)

        asyncio.run(test())

    def test_get_current_user_from_cookie(self):
        """Valid cookie token returns user (lines 156-177)."""
        import asyncio
        from backend.auth import get_current_user

        mock_request = MagicMock()
        mock_request.cookies.get.return_value = "valid_token"

        mock_user = MagicMock(username="testuser")
        mock_session = MagicMock(user_id=1, token_hash=_hash_token("valid_token"), expires_at=datetime.now(UTC) + timedelta(hours=1))

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = (mock_session, mock_user)
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def test():
            user = await get_current_user(mock_request, authorization=None, db=mock_db)
            self.assertEqual(user.username, "testuser")

        asyncio.run(test())

    def test_get_current_user_from_header(self):
        """Valid Authorization header returns user (lines 161-177)."""
        import asyncio
        from backend.auth import get_current_user

        mock_request = MagicMock()
        mock_request.cookies.get.return_value = None

        mock_user = MagicMock(username="testuser")
        mock_session = MagicMock(user_id=1, token_hash=_hash_token("header_token"), expires_at=datetime.now(UTC) + timedelta(hours=1))

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = (mock_session, mock_user)
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def test():
            user = await get_current_user(mock_request, authorization="Bearer header_token", db=mock_db)
            self.assertEqual(user.username, "testuser")

        asyncio.run(test())


class CleanExpiredSessionsTests(unittest.TestCase):
    """Tests for _clean_expired_sessions function (lines 91-98)."""

    def test_clean_expired_sessions_deletes_expired(self):
        """Expired sessions are deleted (lines 94-98)."""
        import asyncio
        from backend.auth import _clean_expired_sessions

        mock_expired_session1 = MagicMock()
        mock_expired_session2 = MagicMock()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_expired_session1, mock_expired_session2]
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def test():
            await _clean_expired_sessions(mock_db)
            self.assertEqual(mock_db.delete.call_count, 2)
            mock_db.commit.assert_called_once()

        asyncio.run(test())


class CreateSessionTests(unittest.TestCase):
    """Tests for _create_session function (lines 101-147)."""

    def test_create_session_creates_new_session(self):
        """Creates new session and returns token (lines 101-118)."""
        import asyncio
        from backend.auth import _create_session

        mock_user = MagicMock(id=1, username="testuser")
        mock_db = AsyncMock()

        # Create proper mock result
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_response = MagicMock()
        mock_response.set_cookie = MagicMock()

        async def test():
            result = await _create_session(mock_user, mock_db, mock_response)

            # Check session was added
            mock_db.add.assert_called()
            mock_db.commit.assert_called()
            # Check result
            self.assertIsInstance(result.access_token, str)
            self.assertEqual(result.username, "testuser")
            # Check cookies were set
            self.assertEqual(mock_response.set_cookie.call_count, 2)

        asyncio.run(test())

    def test_create_session_without_response(self):
        """Works when no response object provided (lines 120-144)."""
        import asyncio
        from backend.auth import _create_session

        mock_user = MagicMock(id=1, username="testuser")
        mock_db = AsyncMock()

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        async def test():
            result = await _create_session(mock_user, mock_db, None)
            self.assertIsInstance(result.access_token, str)
            self.assertEqual(result.username, "testuser")
            self.assertIsNone(result.csrf_token)

        asyncio.run(test())


class VerifyCsrfTests(unittest.TestCase):
    """Tests for verify_csrf function (lines 68-88)."""

    def test_verify_csrf_skip_get_requests(self):
        """GET requests skip CSRF check (line 70-71)."""
        import asyncio
        from backend.auth import verify_csrf

        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/api/something"

        async def test():
            await verify_csrf(mock_request)  # Should not raise

        asyncio.run(test())

    def test_verify_csrf_skip_skip_paths(self):
        """CSRF skip paths bypass check (lines 72-73)."""
        import asyncio
        from backend.auth import verify_csrf

        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.path = "/api/auth/login"

        async def test():
            await verify_csrf(mock_request)  # Should not raise

        asyncio.run(test())

    def test_verify_csrf_no_cookie_returns(self):
        """No CSRF cookie means no check needed (line 77-78)."""
        import asyncio
        from backend.auth import verify_csrf

        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.path = "/api/test"
        mock_request.cookies.get.return_value = None

        async def test():
            await verify_csrf(mock_request)  # Should not raise

        asyncio.run(test())

    def test_verify_csrf_missing_header_raises(self):
        """Missing header raises 403 (lines 80-85)."""
        import asyncio
        from backend.auth import verify_csrf
        from fastapi import HTTPException

        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.path = "/api/test"
        mock_request.cookies.get.return_value = "csrf_token"
        mock_request.headers.get.return_value = None

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await verify_csrf(mock_request)
            self.assertEqual(ctx.exception.status_code, 403)
            self.assertIn("CSRF token required", ctx.exception.detail)

        asyncio.run(test())

    def test_verify_csrf_invalid_token_raises(self):
        """Invalid token raises 403 (lines 87-88)."""
        import asyncio
        from backend.auth import verify_csrf
        from fastapi import HTTPException

        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.path = "/api/test"
        mock_request.cookies.get.return_value = "csrf_token"
        mock_request.headers.get.return_value = "wrong_token"

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await verify_csrf(mock_request)
            self.assertEqual(ctx.exception.status_code, 403)
            self.assertIn("Invalid CSRF token", ctx.exception.detail)

        asyncio.run(test())

    def test_verify_csrf_valid_token_passes(self):
        """Valid token passes (line 88)."""
        import asyncio
        from backend.auth import verify_csrf

        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.path = "/api/test"
        mock_request.cookies.get.return_value = "csrf_token"
        mock_request.headers.get.return_value = "csrf_token"

        async def test():
            await verify_csrf(mock_request)  # Should not raise

        asyncio.run(test())


class LogoutTests(unittest.TestCase):
    """Tests for logout endpoint (lines 353-375)."""

    def test_logout_deletes_session_and_cookies(self):
        """Deletes server session and clears cookies (lines 362-375)."""
        import asyncio
        from backend.auth import logout
        from fastapi import HTTPException

        mock_request = MagicMock()
        mock_request.cookies.get.return_value = "valid_token"

        mock_user = MagicMock(id=1)
        mock_session = MagicMock()

        mock_db = AsyncMock()
        # logout uses db.scalar() directly
        mock_db.scalar = AsyncMock(return_value=mock_session)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        mock_response = MagicMock()

        async def test():
            await logout(mock_response, mock_request, authorization=None, db=mock_db, user=mock_user)
            mock_db.delete.assert_called_with(mock_session)
            mock_db.commit.assert_called()
            self.assertEqual(mock_response.delete_cookie.call_count, 2)

        asyncio.run(test())

    def test_logout_with_header_token(self):
        """Uses Authorization header when no cookie (lines 363-364)."""
        import asyncio
        from backend.auth import logout

        mock_request = MagicMock()
        mock_request.cookies.get.return_value = None

        mock_user = MagicMock(id=1)
        mock_session = MagicMock()

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=mock_session)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        mock_response = MagicMock()

        async def test():
            await logout(mock_response, mock_request, authorization="Bearer header_token", db=mock_db, user=mock_user)
            mock_db.delete.assert_called_with(mock_session)
            mock_db.commit.assert_called()

        asyncio.run(test())

    def test_logout_no_token_just_clears_cookies(self):
        """No token just clears cookies (lines 365-375)."""
        import asyncio
        from backend.auth import logout

        mock_request = MagicMock()
        mock_request.cookies.get.return_value = None

        mock_user = MagicMock(id=1)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.execute.return_value.scalar.return_value = None

        mock_response = MagicMock()

        async def test():
            await logout(mock_response, mock_request, authorization=None, db=mock_db, user=mock_user)
            mock_db.delete.assert_not_called()
            self.assertEqual(mock_response.delete_cookie.call_count, 2)

        asyncio.run(test())


class AuthStatusTestsCoverage(unittest.TestCase):
    """Tests for auth_status endpoint (line 182)."""

    def test_auth_status_no_users(self):
        """When no users, registration is open (line 182)."""
        import asyncio
        from backend.auth import auth_status

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=0)

        async def test():
            result = await auth_status(mock_db)
            self.assertTrue(result.registration_open)

        asyncio.run(test())

    def test_auth_status_users_exist(self):
        """When users exist, registration is closed (line 182)."""
        import asyncio
        from backend.auth import auth_status

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=1)

        async def test():
            result = await auth_status(mock_db)
            self.assertFalse(result.registration_open)

        asyncio.run(test())


class HashTests(unittest.TestCase):
    """Tests for password/hash functions."""

    def test_hash_password_consistency(self):
        """Same password and salt produces same hash."""
        from backend.auth import _hash_password, _hash_token, _issue_token
        import os

        # Use environment variable for test password, fallback to generated one
        test_password = os.environ.get("E2E_TEST_PASSWORD", "AutoGeneratedTestPass123!")
        salt = "abcdef1234567890"
        hash1 = _hash_password(test_password, salt)
        hash2 = _hash_password(test_password, salt)
        self.assertEqual(hash1, hash2)

    def test_hash_token_consistency(self):
        """Same token produces same hash."""
        from backend.auth import _hash_token

        token = "test_token_123"
        hash1 = _hash_token(token)
        hash2 = _hash_token(token)
        self.assertEqual(hash1, hash2)

    def test_issue_token_length(self):
        """Token has expected length."""
        from backend.auth import _issue_token, _issue_csrf_token

        token = _issue_token()
        csrf = _issue_csrf_token()

        self.assertGreater(len(token), 20)
        self.assertGreater(len(csrf), 10)


if __name__ == "__main__":
    unittest.main()
