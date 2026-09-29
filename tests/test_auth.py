import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

from backend.auth import _hash_password, _hash_token, _issue_token


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
