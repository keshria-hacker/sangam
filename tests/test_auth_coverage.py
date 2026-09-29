"""
Tests for auth.py branch coverage - targeting uncovered lines:
- 197, 199, 201 - password validation branches in register (uppercase, lowercase, digit)
- 222 - login invalid credentials
- 253 - forgot password user not found (vague message path)
- 282-288 - production mode logging
- 311, 313, 315 - password validation in reset_password (uppercase, lowercase, digit)

Note: Lines 195 and 309 (password length) are validated by Pydantic schema before reaching
the auth functions, so they're effectively unreachable via normal API path.
"""
import os
import sys
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import UTC, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mainfiles"))

os.environ["TEST_MODE"] = "1"
from cryptography.fernet import Fernet
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key

# Import auth functions for test utilities
from backend.auth import _hash_token

from backend.schemas import AuthCredentialsIn, ForgotPasswordIn, ResetPasswordIn


def _make_mock_db(scalar_returns, execute_returns=None):
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

        mock_db = _make_mock_db([0, None])  # user count = 0, _clean_expired_sessions = None
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

        mock_db = _make_mock_db([0, None])
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

        mock_db = _make_mock_db([0, None])
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
        mock_db = _make_mock_db([None])
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

        mock_db = _make_mock_db([None])  # user not found

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
        mock_db = _make_mock_db([mock_token])

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
        mock_db = _make_mock_db([mock_token])

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
        mock_db = _make_mock_db([mock_token])

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

        mock_db = _make_mock_db([mock_user, None, None], execute_returns=mock_result)
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


class AuthStatusTests(unittest.TestCase):
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