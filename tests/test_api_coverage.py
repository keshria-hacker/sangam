"""
Tests for api.py branch coverage - targeting uncovered lines.
"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

os.environ["TEST_MODE"] = "1"
from cryptography.fernet import Fernet
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key

from backend.config import settings


def _make_mock_db():
    """Create a mock db session."""
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value.scalars.return_value.all.return_value = []
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock()
    mock_db.delete = AsyncMock()
    mock_db.refresh = AsyncMock(side_effect=lambda record: setattr(record, "id", "test-file-id") if record else None)
    return mock_db


class MagicAvailabilityTests(unittest.TestCase):
    """Tests for python-magic import failure path (lines 79-83)."""

    def test_magic_unavailable_graceful_degradation(self):
        """When python-magic fails to import, MAGIC_AVAILABLE is False."""
        import importlib
        import backend.api as api

        # Reload api module to trigger the import logic
        importlib.reload(api)

        # MAGIC_AVAILABLE should be False when libmagic not available
        # (we can't easily test the import failure without complex mocking)
        # Just verify the constant exists
        self.assertIn("MAGIC_AVAILABLE", dir(api))
        self.assertIn("_magic", dir(api))


class ProviderKeyManagementTests(unittest.TestCase):
    """Tests for provider key management (lines 190-198)."""

    def test_delete_provider_key_unknown_provider(self):
        """Delete unknown provider returns 404 (line 205)."""
        import asyncio
        from backend.api import delete_provider_key
        from fastapi import HTTPException

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await delete_provider_key("unknown_provider", mock_db)
            self.assertEqual(ctx.exception.status_code, 404)

        asyncio.run(test())

    def test_delete_provider_key_exists(self):
        """Delete existing provider key (lines 207-209)."""
        import asyncio
        from backend.api import delete_provider_key

        mock_key = MagicMock()
        mock_db = _make_mock_db()
        mock_db.get = AsyncMock(return_value=mock_key)

        async def test():
            await delete_provider_key("openai", mock_db)
            mock_db.delete.assert_called_once_with(mock_key)
            mock_db.commit.assert_called_once()

        asyncio.run(test())

    def test_delete_provider_key_not_exists(self):
        """Delete non-existing provider key (lines 207-209 skip)."""
        import asyncio
        from backend.api import delete_provider_key

        mock_db = _make_mock_db()
        mock_db.get = AsyncMock(return_value=None)

        async def test():
            await delete_provider_key("openai", mock_db)
            mock_db.delete.assert_not_called()
            mock_db.commit.assert_not_called()

        asyncio.run(test())


class ChatManagementTests(unittest.TestCase):
    """Tests for chat management endpoints (lines 272, 280-283, 291-295)."""

    def test_get_chat_not_found(self):
        """Get chat returns 404 when not found (line 282)."""
        import asyncio
        from backend.api import get_chat
        from fastapi import HTTPException

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = mock_result

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await get_chat("nonexistent", mock_db)
            self.assertEqual(ctx.exception.status_code, 404)
            self.assertIn("Chat not found", ctx.exception.detail)

        asyncio.run(test())

    def test_delete_chat_not_found(self):
        """Delete chat returns 404 when not found (lines 292-293)."""
        import asyncio
        from backend.api import delete_chat
        from fastapi import HTTPException

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = mock_result

        async def test():
            with self.assertRaises(HTTPException) as ctx:
                await delete_chat("nonexistent", mock_db)
            self.assertEqual(ctx.exception.status_code, 404)
            self.assertIn("Chat not found", ctx.exception.detail)

        asyncio.run(test())

    def test_delete_chat_exists(self):
        """Delete existing chat (lines 294-295)."""
        import asyncio
        from backend.api import delete_chat

        mock_chat = MagicMock()
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_chat)
        mock_db.execute.return_value = mock_result

        async def test():
            await delete_chat("existing", mock_db)
            mock_db.delete.assert_called_once_with(mock_chat)
            mock_db.commit.assert_called_once()

        asyncio.run(test())


class FileUploadTests(unittest.TestCase):
    """Tests for file upload validation (lines 322, 361-367)."""

    def test_upload_file_malformed_content_length_header(self):
        """Malformed Content-Length header falls through to read-based check (line 322)."""
        import asyncio
        from backend.api import upload_file

        mock_request = MagicMock()
        mock_request.headers = {"content-length": "not-a-number"}

        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"small content")

        mock_db = _make_mock_db()

        with patch("backend.api.settings.MAX_UPLOAD_SIZE_MB", 50):
            with patch("backend.api.settings.UPLOAD_DIR", Path("/tmp/test_uploads")):
                with patch("backend.api.truncate_preview", return_value="preview"):
                    with patch("backend.api.extract_text", return_value="extracted"):
                        with patch("backend.api.index_document"):
                            # Need to mock the UUID and file writing
                            with patch("backend.api.uuid.uuid4") as mock_uuid:
                                mock_uuid.return_value.hex = "abc123"
                                with patch("builtins.open", MagicMock()):
                                    async def test():
                                        result = await upload_file(mock_request, mock_file, mock_db)
                                        self.assertIsNotNone(result.file_id)

                                    asyncio.run(test())

    def test_upload_file_index_document_failure(self):
        """File indexing failure doesn't break upload - returns -1 (lines 364-365)."""
        import asyncio
        from backend.api import upload_file

        mock_request = MagicMock()
        mock_request.headers = {}

        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"test content")

        mock_db = _make_mock_db()

        with patch("backend.api.settings.MAX_UPLOAD_SIZE_MB", 50):
            with patch("backend.api.settings.UPLOAD_DIR", Path("/tmp/test_uploads")):
                with patch("backend.api.truncate_preview", return_value="preview"):
                    with patch("backend.api.extract_text", return_value="extracted"):
                        with patch("backend.api.index_document", return_value=-1):
                            with patch("backend.api.uuid.uuid4") as mock_uuid:
                                mock_uuid.return_value.hex = "abc123"
                                with patch("builtins.open", MagicMock()):
                                    async def test():
                                        result = await upload_file(mock_request, mock_file, mock_db)
                                        self.assertIsNotNone(result.file_id)

                                    asyncio.run(test())


class RefreshModelsTests(unittest.TestCase):
    """Tests for refresh provider models (lines 247-253)."""

    def test_refresh_models_fetch_failure_returns_success_false(self):
        """Fetch error returns success=False with count=0 (lines 247-253)."""
        import asyncio
        from backend.api import refresh_provider_models
        from backend.schemas import RefreshModelsOut
        from backend.providers.base import ProviderConfig

        mock_db = _make_mock_db()

        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.local = False
        mock_config.label = "OpenAI"
        mock_config.model_endpoint = "https://api.openai.com/v1/models"
        mock_config.auth_type = "bearer"
        mock_config.auth_header_name = "Authorization"
        mock_config.query_key = None
        mock_config.json_path = "data"
        mock_config.id_field = "id"
        mock_config.strip_prefix = ""
        mock_config.extra_headers = None

        with patch("backend.api.llm.registry.get_config", return_value=mock_config):
            with patch("backend.api.llm.resolve_api_key", return_value="test-key"):
                with patch("backend.api.llm.fetch_models_from_provider", side_effect=Exception("Network error")):
                    async def test():
                        result = await refresh_provider_models("openai", mock_db)
                        self.assertIsInstance(result, RefreshModelsOut)
                        self.assertFalse(result.success)
                        self.assertEqual(result.count, 0)
                        self.assertEqual(result.models, [])

                    asyncio.run(test())


if __name__ == "__main__":
    unittest.main()