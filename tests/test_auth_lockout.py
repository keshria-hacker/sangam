"""
Tests for the brute-force login lockout (audit C-007).

A username is locked out after MAX_LOGIN_ATTEMPTS consecutive failed
logins for LOGIN_LOCKOUT_SECONDS (sliding window), using the shared
rate-limit store. Successful logins reset the failure counter so valid
users never lock themselves out.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mainfiles"))

os.environ["TEST_MODE"] = "1"
from cryptography.fernet import Fernet
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key

from backend.auth import MAX_LOGIN_ATTEMPTS, login  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from backend.ratelimit_redis import MemoryStore, reset_rate_limit_store_for_testing  # noqa: E402
from backend.schemas import AuthCredentialsIn  # noqa: E402


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
