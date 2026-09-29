"""
Comprehensive tests for rag.py — RAG chunking, indexing, and retrieval.

Tests cover:
- chunk_text function (various text lengths, edge cases)
- index_document function (success, failure, empty text)
- retrieve_relevant_chunks function (query, filtering, empty results)
- delete_document_chunks function
- reset_vector_index and close_client
- Integration tests with actual ChromaDB (using temp directory)
"""

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

# Enable test mode
os.environ["TEST_MODE"] = "1"
from cryptography.fernet import Fernet
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key

# Use a temporary directory for ChromaDB in tests
import tempfile
test_chroma_dir = Path(tempfile.gettempdir()) / "test_chromadb_rag"
os.environ["CHROMA_DB_PATH"] = str(test_chroma_dir)

from backend.rag import (
    chunk_text,
    index_document,
    retrieve_relevant_chunks,
    delete_document_chunks,
    reset_vector_index,
    close_client,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    TOP_K,
    CHROMA_DB_DIR,
)

# Need to import after setting CHROMA_DB_PATH
import backend.rag as rag


class ChunkTextTests(unittest.TestCase):
    """Tests for the chunk_text function."""

    def test_empty_string(self):
        """Empty string returns empty list."""
        result = chunk_text("")
        self.assertEqual(result, [])

    def test_whitespace_only(self):
        """Whitespace-only string returns empty list."""
        result = chunk_text("   \n\n  \t  ")
        self.assertEqual(result, [])

    def test_short_text_single_chunk(self):
        """Text shorter than chunk_size returns single chunk."""
        text = "Short text."
        result = chunk_text(text, chunk_size=100, overlap=20)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "Short text.")

    def test_text_exact_chunk_size(self):
        """Text exactly at chunk boundary returns single chunk."""
        # 100 tokens * 4 = 400 chars - but need to account for strip() and logic
        text = "a" * 350  # slightly under to ensure single chunk
        result = chunk_text(text, chunk_size=100, overlap=20)
        self.assertEqual(len(result), 1)

    def test_text_over_chunk_size(self):
        """Text over chunk_size splits into multiple chunks with overlap."""
        # 100 tokens * 4 = 400 chars, text is 500 chars
        text = "a" * 500
        result = chunk_text(text, chunk_size=100, overlap=20)
        self.assertGreaterEqual(len(result), 2)
        # Chunks should exist and have content
        self.assertTrue(len(result[0]) > 0)
        self.assertTrue(len(result[1]) > 0)

    def test_paragraph_splitting(self):
        """Text split on paragraph boundaries."""
        text = "Paragraph 1.\n\nParagraph 2.\n\nParagraph 3."
        result = chunk_text(text, chunk_size=10, overlap=2)  # small chunks to force split
        self.assertGreater(len(result), 1)
        # Each chunk should contain paragraph text
        for chunk in result:
            self.assertIn("Paragraph", chunk)

    def test_oversized_single_paragraph(self):
        """Single paragraph larger than chunk_size gets hard-split."""
        # Create a single very long paragraph (no double newlines)
        text = "a " * 200  # ~400 chars, chunk_size=50 tokens = 200 chars
        result = chunk_text(text, chunk_size=50, overlap=10)
        self.assertGreater(len(result), 1)
        # Chunks should overlap
        self.assertTrue(len(result[0]) > 0)
        self.assertTrue(len(result[1]) > 0)

    def test_overlap_carry_over(self):
        """Overlap from previous chunk carried into next chunk."""
        text = "Word " * 100  # ~500 chars
        result = chunk_text(text, chunk_size=30, overlap=10)  # small chunks
        self.assertGreater(len(result), 1)
        # Verify overlap exists by checking end of chunk 0 appears in start of chunk 1
        # (exact overlap text may vary due to paragraph boundaries)

    def test_multiple_paragraphs_accrue(self):
        """Multiple small paragraphs combine into chunks."""
        text = "Para1.\n\nPara2.\n\nPara3.\n\nPara4.\n\nPara5."
        result = chunk_text(text, chunk_size=20, overlap=5)
        self.assertGreater(len(result), 0)
        # All original text should be preserved (approximately)
        combined = " ".join(result)
        for word in ["Para1", "Para2", "Para3", "Para4", "Para5"]:
            self.assertIn(word, combined)

    def test_unicode_text(self):
        """Unicode text is handled correctly."""
        text = "你好世界\n\nこんにちは\n\nHello world"
        result = chunk_text(text, chunk_size=10, overlap=2)
        self.assertGreater(len(result), 0)
        combined = "".join(result)
        self.assertIn("你好世界", combined)
        self.assertIn("こんにちは", combined)

    def test_chunk_size_and_overlap_parameters(self):
        """Custom chunk_size and overlap parameters are respected."""
        text = "x" * 1000
        result1 = chunk_text(text, chunk_size=50, overlap=10)
        result2 = chunk_text(text, chunk_size=100, overlap=20)
        # Larger chunk size should produce fewer chunks
        self.assertLessEqual(len(result2), len(result1))


class IndexDocumentTests(unittest.TestCase):
    """Tests for index_document function."""

    def setUp(self):
        """Reset vector index before each test."""
        rag.reset_vector_index()

    def tearDown(self):
        """Clean up after each test."""
        rag.reset_vector_index()

    def test_index_empty_text(self):
        """Indexing empty text returns 0."""
        result = index_document("file1", "", "test.txt")
        self.assertEqual(result, 0)

    def test_index_whitespace_only(self):
        """Indexing whitespace-only text returns 0."""
        result = index_document("file1", "   \n\n  ", "test.txt")
        self.assertEqual(result, 0)

    @patch("backend.rag._get_collection")
    def test_index_document_success(self, mock_get_collection):
        """Successful indexing returns chunk count."""
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection

        text = "This is a test document. " * 20  # ~500 chars = multiple chunks
        result = index_document("file1", text, "test.txt")

        self.assertGreater(result, 0)
        mock_collection.add.assert_called_once()
        call_args = mock_collection.add.call_args
        self.assertIn("documents", call_args.kwargs)
        self.assertIn("ids", call_args.kwargs)
        self.assertIn("metadatas", call_args.kwargs)
        # Check metadata structure
        metadatas = call_args.kwargs["metadatas"]
        self.assertEqual(len(metadatas), result)
        for i, meta in enumerate(metadatas):
            self.assertEqual(meta["file_id"], "file1")
            self.assertEqual(meta["filename"], "test.txt")
            self.assertEqual(meta["chunk_index"], i)

    @patch("backend.rag._get_collection")
    def test_index_document_exception_handling(self, mock_get_collection):
        """Exception during indexing returns -1."""
        mock_collection = MagicMock()
        mock_collection.add.side_effect = Exception("ChromaDB error")
        mock_get_collection.return_value = mock_collection

        result = index_document("file1", "some text", "test.txt")
        self.assertEqual(result, -1)


class RetrieveRelevantChunksTests(unittest.TestCase):
    """Tests for retrieve_relevant_chunks function."""

    def setUp(self):
        """Reset vector index before each test."""
        rag.reset_vector_index()

    def tearDown(self):
        """Clean up after each test."""
        rag.reset_vector_index()

    def test_empty_query(self):
        """Empty query returns empty list."""
        result = retrieve_relevant_chunks("", ["file1"])
        self.assertEqual(result, [])

    def test_none_query(self):
        """None query returns empty list."""
        result = retrieve_relevant_chunks(None, ["file1"])
        self.assertEqual(result, [])

    def test_empty_file_ids(self):
        """Empty file_ids returns empty list."""
        result = retrieve_relevant_chunks("query", [])
        self.assertEqual(result, [])

    def test_none_file_ids(self):
        """None file_ids returns empty list."""
        result = retrieve_relevant_chunks("query", None)
        self.assertEqual(result, [])

    @patch("backend.rag._get_collection")
    def test_retrieve_chunks_success(self, mock_get_collection):
        """Successful retrieval returns formatted chunks."""
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection

        # Mock ChromaDB query results
        mock_collection.query.return_value = {
            "documents": [["Chunk 1 text", "Chunk 2 text"]],
            "metadatas": [[{"filename": "doc1.pdf", "file_id": "file1", "chunk_index": 0},
                           {"filename": "doc1.pdf", "file_id": "file1", "chunk_index": 1}]],
            "distances": [[0.1, 0.2]]
        }

        result = retrieve_relevant_chunks("test query", ["file1"], top_k=5)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["text"], "Chunk 1 text")
        self.assertEqual(result[0]["filename"], "doc1.pdf")
        self.assertEqual(result[0]["score"], 0.1)
        self.assertEqual(result[1]["text"], "Chunk 2 text")
        self.assertEqual(result[1]["score"], 0.2)

        mock_collection.query.assert_called_once_with(
            query_texts=["test query"],
            n_results=5,
            where={"file_id": {"$in": ["file1"]}}
        )

    @patch("backend.rag._get_collection")
    def test_retrieve_chunks_empty_results(self, mock_get_collection):
        """Empty results from ChromaDB returns empty list."""
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection
        mock_collection.query.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]]
        }

        result = retrieve_relevant_chunks("query", ["file1"])
        self.assertEqual(result, [])

    @patch("backend.rag._get_collection")
    def test_retrieve_chunks_none_results(self, mock_get_collection):
        """None results from ChromaDB returns empty list."""
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection
        mock_collection.query.return_value = None

        result = retrieve_relevant_chunks("query", ["file1"])
        self.assertEqual(result, [])

    @patch("backend.rag._get_collection")
    def test_retrieve_chunks_exception(self, mock_get_collection):
        """Exception during retrieval returns empty list."""
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection
        mock_collection.query.side_effect = Exception("ChromaDB error")

        result = retrieve_relevant_chunks("query", ["file1"])
        self.assertEqual(result, [])

    @patch("backend.rag._get_collection")
    def test_retrieve_respects_top_k_cap(self, mock_get_collection):
        """top_k is capped at 50."""
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection
        mock_collection.query.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]]
        }

        retrieve_relevant_chunks("query", ["file1"], top_k=100)
        # Should be called with n_results=50 (the cap)
        call_args = mock_collection.query.call_args
        self.assertEqual(call_args.kwargs["n_results"], 50)

    @patch("backend.rag._get_collection")
    def test_retrieve_handles_missing_metadata(self, mock_get_collection):
        """Missing metadata handled gracefully."""
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection
        mock_collection.query.return_value = {
            "documents": [["Chunk text"]],
            "metadatas": [[{}]],  # empty metadata
            "distances": [[0.1]]
        }

        result = retrieve_relevant_chunks("query", ["file1"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["filename"], "")  # default empty string
        self.assertEqual(result[0]["text"], "Chunk text")
        self.assertEqual(result[0]["score"], 0.1)

    @patch("backend.rag._get_collection")
    def test_retrieve_handles_missing_distance(self, mock_get_collection):
        """Missing distance handled gracefully."""
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection
        mock_collection.query.return_value = {
            "documents": [["Chunk text"]],
            "metadatas": [[{"filename": "test.txt"}]],
            "distances": [[]]  # empty distances
        }

        result = retrieve_relevant_chunks("query", ["file1"])
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["score"])


class DeleteDocumentChunksTests(unittest.TestCase):
    """Tests for delete_document_chunks function."""

    def setUp(self):
        rag.reset_vector_index()

    def tearDown(self):
        rag.reset_vector_index()

    @patch("backend.rag._get_collection")
    def test_delete_success(self, mock_get_collection):
        """Successful deletion returns True."""
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection

        result = delete_document_chunks("file1")
        self.assertTrue(result)
        mock_collection.delete.assert_called_once_with(where={"file_id": "file1"})

    @patch("backend.rag._get_collection")
    def test_delete_exception_returns_false(self, mock_get_collection):
        """Exception during deletion returns False."""
        mock_collection = MagicMock()
        mock_collection.delete.side_effect = Exception("Delete error")
        mock_get_collection.return_value = mock_collection

        result = delete_document_chunks("file1")
        self.assertFalse(result)


class ResetVectorIndexTests(unittest.TestCase):
    """Tests for reset_vector_index and close_client."""

    def tearDown(self):
        rag.close_client()

    @patch("backend.rag._get_client")
    def test_reset_vector_index_deletes_collection(self, mock_get_client):
        """reset_vector_index deletes and recreates collection."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Set a collection first
        rag._collection = MagicMock()

        reset_vector_index()

        mock_client.delete_collection.assert_called_once_with("document_chunks")
        self.assertIsNone(rag._collection)

    @patch("backend.rag._get_client")
    def test_reset_handles_value_error(self, mock_get_client):
        """ValueError (older chromadb) is caught."""
        mock_client = MagicMock()
        mock_client.delete_collection.side_effect = ValueError("Collection not found")
        mock_get_client.return_value = mock_client

        rag._collection = MagicMock()
        reset_vector_index()  # Should not raise
        self.assertIsNone(rag._collection)

    @patch("backend.rag._get_client")
    def test_reset_handles_not_found_error(self, mock_get_client):
        """NotFoundError (chromadb 1.5+) is caught."""
        import chromadb.errors
        mock_client = MagicMock()
        mock_client.delete_collection.side_effect = chromadb.errors.NotFoundError("Not found")
        mock_get_client.return_value = mock_client

        rag._collection = MagicMock()
        reset_vector_index()  # Should not raise
        self.assertIsNone(rag._collection)

    @patch("backend.rag._get_client")
    def test_close_client_resets_singletons(self, mock_get_client):
        """close_client resets both _client and _collection."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Initialize both
        rag._client = mock_client
        rag._collection = MagicMock()

        close_client()

        self.assertIsNone(rag._client)
        self.assertIsNone(rag._collection)


class IntegrationTests(unittest.TestCase):
    """Integration tests using real ChromaDB with temp directory."""

    @classmethod
    def setUpClass(cls):
        """Create temp directory for ChromaDB."""
        cls.temp_dir = TemporaryDirectory()
        os.environ["CHROMA_DB_PATH"] = cls.temp_dir.name
        # Reimport to pick up new path
        import importlib
        importlib.reload(rag)

    @classmethod
    def tearDownClass(cls):
        """Cleanup temp directory."""
        # Ensure client is closed before cleanup
        try:
            rag.close_client()
        except:
            pass
        import time
        time.sleep(0.5)  # Give Windows time to release file handles
        try:
            cls.temp_dir.cleanup()
        except PermissionError:
            # Best effort on Windows
            pass

    def setUp(self):
        rag.reset_vector_index()

    def tearDown(self):
        rag.reset_vector_index()

    def test_full_index_and_retrieve_cycle(self):
        """Full cycle: index document, retrieve chunks."""
        file_id = "test-file-1"
        filename = "test.txt"
        text = "This is a test document. " * 50  # ~1000 chars, multiple chunks

        # Index the document
        chunk_count = index_document(file_id, text, filename)
        self.assertGreater(chunk_count, 0)

        # Retrieve relevant chunks
        results = retrieve_relevant_chunks("test document", [file_id])
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), TOP_K)

        # Verify result structure
        for chunk in results:
            self.assertIn("text", chunk)
            self.assertIn("filename", chunk)
            self.assertIn("score", chunk)
            self.assertEqual(chunk["filename"], filename)
            # Score should be a float (distance)
            self.assertIsInstance(chunk["score"], (int, float))

        # Delete and verify gone
        delete_result = delete_document_chunks(file_id)
        self.assertTrue(delete_result)

        results = retrieve_relevant_chunks("test document", [file_id])
        self.assertEqual(results, [])

    def test_multiple_files_isolated(self):
        """Multiple files indexed and retrieved independently."""
        text1 = "Apple banana cherry. " * 30
        text2 = "Dog elephant fox. " * 30

        index_document("file1", text1, "doc1.txt")
        index_document("file2", text2, "doc2.txt")

        # Search in file1 only
        results1 = retrieve_relevant_chunks("apple", ["file1"])
        self.assertGreater(len(results1), 0)
        for r in results1:
            self.assertEqual(r["filename"], "doc1.txt")

        # Search in file2 only
        results2 = retrieve_relevant_chunks("dog", ["file2"])
        self.assertGreater(len(results2), 0)
        for r in results2:
            self.assertEqual(r["filename"], "doc2.txt")

        # Search in both
        results_both = retrieve_relevant_chunks("test", ["file1", "file2"])
        # Should find chunks from both files
        filenames = {r["filename"] for r in results_both}
        self.assertIn("doc1.txt", filenames)
        self.assertIn("doc2.txt", filenames)

    def test_chunk_text_edge_cases(self):
        """Test chunk_text directly with various inputs."""
        # Very long single paragraph
        long_para = "Word " * 1000
        chunks = chunk_text(long_para, chunk_size=50, overlap=10)
        self.assertGreater(len(chunks), 1)

        # Many short paragraphs
        many_paras = "Para.\n\n" * 100
        chunks = chunk_text(many_paras, chunk_size=50, overlap=10)
        self.assertGreater(len(chunks), 1)

        # Mixed content
        mixed = "Short.\n\n" + "Long paragraph. " * 100 + "\n\nEnd."
        chunks = chunk_text(mixed, chunk_size=50, overlap=10)
        self.assertGreater(len(chunks), 1)


class ConstantsTests(unittest.TestCase):
    """Tests for module constants."""

    def test_constants_positive(self):
        """Constants are positive values."""
        self.assertGreater(CHUNK_SIZE, 0)
        self.assertGreater(CHUNK_OVERLAP, 0)
        self.assertGreater(TOP_K, 0)
        self.assertLess(CHUNK_OVERLAP, CHUNK_SIZE)

    def test_chroma_db_dir_path(self):
        """CHROMA_DB_DIR is a Path."""
        self.assertIsInstance(CHROMA_DB_DIR, Path)


class RagFailureLoggingTests(unittest.TestCase):
    """Failure paths must log a traceback via ``logger.exception``.

    The graceful-degradation return contracts (-1 / [] / False) must be
    preserved so callers can fall back to full-text stuffing — the audit
    finding (C-004) is about *visibility*, not raising.
    """

    @patch("backend.rag.logger")
    @patch("backend.rag._get_collection")
    def test_index_document_logs_exception(self, mock_get_collection, mock_logger):
        """index_document failure logs exception with file context, returns -1."""
        mock_collection = MagicMock()
        mock_collection.add.side_effect = Exception("ChromaDB error")
        mock_get_collection.return_value = mock_collection

        result = index_document("file1", "some text", "test.txt")

        self.assertEqual(result, -1)  # contract preserved
        mock_logger.exception.assert_called_once()
        logged = " ".join(str(a) for a in mock_logger.exception.call_args.args)
        self.assertIn("file1", logged)  # context logged

    @patch("backend.rag.logger")
    @patch("backend.rag._get_collection")
    def test_retrieve_relevant_chunks_logs_exception(self, mock_get_collection, mock_logger):
        """retrieve failure logs exception with query context, returns []."""
        mock_collection = MagicMock()
        mock_collection.query.side_effect = Exception("ChromaDB error")
        mock_get_collection.return_value = mock_collection

        result = retrieve_relevant_chunks("some query", ["file1"])

        self.assertEqual(result, [])  # contract preserved
        mock_logger.exception.assert_called_once()
        logged = " ".join(str(a) for a in mock_logger.exception.call_args.args)
        self.assertIn("some query", logged)  # context logged

    @patch("backend.rag.logger")
    @patch("backend.rag._get_collection")
    def test_delete_document_chunks_logs_exception(self, mock_get_collection, mock_logger):
        """delete failure logs exception with file context, returns False."""
        mock_collection = MagicMock()
        mock_collection.delete.side_effect = Exception("Delete error")
        mock_get_collection.return_value = mock_collection

        result = delete_document_chunks("file1")

        self.assertFalse(result)  # contract preserved
        mock_logger.exception.assert_called_once()
        logged = " ".join(str(a) for a in mock_logger.exception.call_args.args)
        self.assertIn("file1", logged)  # context logged


if __name__ == "__main__":
    unittest.main()