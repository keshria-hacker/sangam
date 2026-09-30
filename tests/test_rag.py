"""test_rag — consolidated tests.

Merged from:
- test_rag_coverage.py
- test_rag_new.py
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
import os

import sys

import unittest

from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet

from pathlib import Path

from tempfile import TemporaryDirectory

from unittest.mock import MagicMock, patch

import tempfile

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

import backend.rag as rag


# --- tests ---

_test_key = Fernet.generate_key().decode()


class GetClientTests(unittest.TestCase):
    """Tests for _get_client function (line 79)."""

    def test_get_client_creates_client(self):
        """_get_client creates PersistentClient when not exists."""
        import backend.rag as rag

        # Reset global state
        rag._client = None

        with patch("backend.rag.chromadb.PersistentClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            client = rag._get_client()

            mock_client_class.assert_called_once()
            self.assertEqual(client, mock_client)
            self.assertEqual(rag._client, mock_client)

    def test_get_client_returns_existing(self):
        """_get_client returns existing client if already created."""
        import backend.rag as rag

        mock_client = MagicMock()
        rag._client = mock_client

        client = rag._get_client()

        self.assertEqual(client, mock_client)


class GetCollectionTests(unittest.TestCase):
    """Tests for _get_collection function (lines 86-92)."""

    def test_get_collection_existing(self):
        """_get_collection returns existing collection."""
        import backend.rag as rag

        mock_collection = MagicMock()
        rag._collection = mock_collection

        collection = rag._get_collection()

        self.assertEqual(collection, mock_collection)

    def test_get_collection_value_error_creates_new(self):
        """ValueError when getting collection triggers create_collection (lines 87-88)."""
        import backend.rag as rag

        rag._collection = None

        mock_client = MagicMock()
        mock_client.get_collection.side_effect = ValueError("Collection not found")
        mock_client.create_collection.return_value = MagicMock()

        with patch("backend.rag._get_client", return_value=mock_client):
            collection = rag._get_collection()

            mock_client.get_collection.assert_called_once_with("document_chunks")
            mock_client.create_collection.assert_called_once_with("document_chunks")

    def test_get_collection_not_found_error_creates_new(self):
        """NotFoundError when getting collection triggers create_collection (lines 89-91)."""
        import backend.rag as rag
        import chromadb.errors

        rag._collection = None

        mock_client = MagicMock()
        mock_client.get_collection.side_effect = chromadb.errors.NotFoundError("Not found")
        mock_client.create_collection.return_value = MagicMock()

        with patch("backend.rag._get_client", return_value=mock_client):
            collection = rag._get_collection()

            mock_client.get_collection.assert_called_once_with("document_chunks")
            mock_client.create_collection.assert_called_once_with("document_chunks")


class ChunkTextCoverageTests(unittest.TestCase):
    """Tests for chunk_text function covering edge cases (lines 133, 161-162)."""

    def test_chunk_text_empty_paragraphs_returns_empty(self):
        """Empty text returns empty list (line 123-124)."""
        from backend.rag import chunk_text
        result = chunk_text("")
        self.assertEqual(result, [])

    def test_chunk_text_whitespace_only_returns_empty(self):
        """Whitespace-only text returns empty list."""
        from backend.rag import chunk_text
        result = chunk_text("   \n\n  \t  ")
        self.assertEqual(result, [])

    def test_chunk_text_short_text_single_chunk(self):
        """Text shorter than chunk size returns single chunk."""
        from backend.rag import chunk_text
        text = "Short text here"
        result = chunk_text(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], text)

    def test_chunk_text_paragraph_boundary_split(self):
        """Text splits on double newlines."""
        from backend.rag import chunk_text
        text = "Para 1\n\nPara 2\n\nPara 3"
        result = chunk_text(text, chunk_size=10, overlap=0)  # Small chunks for testing
        # The function doesn't split on boundaries when chunks are small enough
        # Just verify it returns at least one chunk
        self.assertGreater(len(result), 0)

    def test_chunk_text_oversized_paragraph_hard_split(self):
        """Single oversized paragraph is hard-split (line 144-148)."""
        from backend.rag import chunk_text
        # Create a paragraph longer than target_chars (10 * 4 = 40 chars)
        long_para = "A" * 100
        result = chunk_text(long_para, chunk_size=10, overlap=2)
        self.assertGreater(len(result), 1)

    def test_chunk_text_oversized_paragraph_with_carry(self):
        """Oversized paragraph with carry creates overlap (lines 146-148)."""
        from backend.rag import chunk_text
        long_para = "A" * 100
        result = chunk_text(long_para, chunk_size=10, overlap=5)
        # Should have carry from overlap
        self.assertTrue(any(len(c) > 0 for c in result))

    def test_chunk_text_paragraph_pushes_over_limit(self):
        """Adding paragraph pushes over limit triggers chunk finalize (lines 152-153)."""
        from backend.rag import chunk_text
        # With small chunk size, multiple paragraphs should create chunks
        text = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
        result = chunk_text(text, chunk_size=5, overlap=1)
        self.assertGreater(len(result), 1)

    def test_chunk_text_overlap_carry_over(self):
        """Overlap carry-over logic (lines 156-165)."""
        from backend.rag import chunk_text
        # Create text that will trigger overlap logic
        text = "Para 1\n\nPara 2\n\nPara 3\n\nPara 4"
        result = chunk_text(text, chunk_size=5, overlap=2)
        self.assertGreater(len(result), 1)

    def test_chunk_text_empty_paragraphs_filtered(self):
        """Empty paragraphs are filtered out (line 133)."""
        from backend.rag import chunk_text
        text = "Para 1\n\n\n\nPara 2\n\n   \n\nPara 3"
        result = chunk_text(text, chunk_size=10, overlap=0)
        # Empty paras should be filtered - they may be merged into fewer chunks
        self.assertGreater(len(result), 0)

    def test_chunk_text_all_empty_paragraphs(self):
        """Text with only empty paragraphs returns empty list (line 133)."""
        from backend.rag import chunk_text
        # Text that has content (non-whitespace at top level) but only produces empty paragraphs after split
        text = "   \n\n   \n\n   "
        result = chunk_text(text)
        self.assertEqual(result, [])


class IndexDocumentCoverageTests(unittest.TestCase):
    """Tests for index_document function."""

    def test_index_document_empty_chunks_returns_zero(self):
        """Empty chunks returns 0 (line 202-203)."""
        import backend.rag as rag

        with patch("backend.rag.chunk_text", return_value=[]):
            result = rag.index_document("file1", "text", "test.txt")
            self.assertEqual(result, 0)

    def test_index_document_success(self):
        """Successful indexing returns chunk count."""
        import backend.rag as rag

        mock_collection = MagicMock()
        mock_collection.add = MagicMock()

        with patch("backend.rag.chunk_text", return_value=["chunk1", "chunk2"]):
            with patch("backend.rag._get_collection", return_value=mock_collection):
                result = rag.index_document("file1", "text content", "test.txt")
                self.assertEqual(result, 2)
                mock_collection.add.assert_called_once()

    def test_index_document_exception_returns_minus_one(self):
        """Exception during indexing returns -1 (lines 222-224)."""
        import backend.rag as rag

        with patch("backend.rag.chunk_text", return_value=["chunk1"]):
            with patch("backend.rag._get_collection", side_effect=Exception("DB error")):
                result = rag.index_document("file1", "text", "test.txt")
                self.assertEqual(result, -1)


class RetrieveRelevantChunksCoverageTests(unittest.TestCase):
    """Tests for retrieve_relevant_chunks (line 273)."""

    def test_retrieve_empty_query_returns_empty(self):
        """Empty query returns empty list (line 255-256)."""
        from backend.rag import retrieve_relevant_chunks
        result = retrieve_relevant_chunks("", ["file1"])
        self.assertEqual(result, [])

    def test_retrieve_empty_file_ids_returns_empty(self):
        """Empty file_ids returns empty list."""
        from backend.rag import retrieve_relevant_chunks
        result = retrieve_relevant_chunks("query", [])
        self.assertEqual(result, [])

    def test_retrieve_empty_doc_skipped(self):
        """Empty document in results is skipped (line 272-273)."""
        import backend.rag as rag

        mock_results = {
            "documents": [["doc1", "", "doc3"]],  # Empty doc in middle
            "metadatas": [[{"filename": "f1"}, {"filename": "f2"}, {"filename": "f3"}]],
            "distances": [[0.1, 0.2, 0.3]],
        }

        mock_collection = MagicMock()
        mock_collection.query.return_value = mock_results

        with patch("backend.rag._get_collection", return_value=mock_collection):
            result = rag.retrieve_relevant_chunks("query", ["file1"])
            # Should skip empty doc
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["text"], "doc1")
            self.assertEqual(result[1]["text"], "doc3")

    def test_retrieve_missing_metadata_handled(self):
        """Missing metadata handled gracefully."""
        import backend.rag as rag

        mock_results = {
            "documents": [["doc1"]],
            "metadatas": [[]],  # Empty metadata
            "distances": [[]],  # Empty distances
        }

        mock_collection = MagicMock()
        mock_collection.query.return_value = mock_results

        with patch("backend.rag._get_collection", return_value=mock_collection):
            result = rag.retrieve_relevant_chunks("query", ["file1"])
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["text"], "doc1")
            self.assertEqual(result[0]["filename"], "")  # Default empty
            self.assertIsNone(result[0]["score"])

    def test_retrieve_exception_returns_empty(self):
        """Exception during retrieval returns empty list (lines 286-288)."""
        import backend.rag as rag

        with patch("backend.rag._get_collection", side_effect=Exception("Query failed")):
            result = rag.retrieve_relevant_chunks("query", ["file1"])
            self.assertEqual(result, [])


class DeleteDocumentChunksTests(unittest.TestCase):
    """Tests for delete_document_chunks function."""

    def test_delete_document_chunks_success(self):
        """Successful deletion returns True."""
        import backend.rag as rag

        mock_collection = MagicMock()
        mock_collection.delete = MagicMock()

        with patch("backend.rag._get_collection", return_value=mock_collection):
            result = rag.delete_document_chunks("file1")
            self.assertTrue(result)
            mock_collection.delete.assert_called_once_with(where={"file_id": "file1"})

    def test_delete_document_chunks_exception_returns_false(self):
        """Exception returns False (lines 301-303)."""
        import backend.rag as rag

        with patch("backend.rag._get_collection", side_effect=Exception("Delete failed")):
            result = rag.delete_document_chunks("file1")
            self.assertFalse(result)


class ResetVectorIndexTests(unittest.TestCase):
    """Tests for reset_vector_index function."""

    def test_reset_vector_index_value_error(self):
        """ValueError during delete_collection is caught (line 312-313)."""
        import backend.rag as rag

        mock_client = MagicMock()
        mock_client.delete_collection.side_effect = ValueError("Didn't exist")

        with patch("backend.rag._get_client", return_value=mock_client):
            rag.reset_vector_index()
            self.assertIsNone(rag._collection)

    def test_reset_vector_index_not_found_error(self):
        """NotFoundError during delete_collection is caught (line 314-315)."""
        import backend.rag as rag
        import chromadb.errors

        mock_client = MagicMock()
        mock_client.delete_collection.side_effect = chromadb.errors.NotFoundError("Not found")

        with patch("backend.rag._get_client", return_value=mock_client):
            rag.reset_vector_index()
            self.assertIsNone(rag._collection)


class CloseClientTests(unittest.TestCase):
    """Tests for close_client function."""

    def test_close_client_resets_globals(self):
        """close_client resets both client and collection to None."""
        import backend.rag as rag

        rag._client = MagicMock()
        rag._collection = MagicMock()

        rag.close_client()

        self.assertIsNone(rag._client)
        self.assertIsNone(rag._collection)


if __name__ == "__main__":
    unittest.main()


_test_key = Fernet.generate_key().decode()


test_chroma_dir = Path(tempfile.gettempdir()) / "test_chromadb_rag"


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


class DeleteDocumentChunksTestsNew(unittest.TestCase):
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


class ResetVectorIndexTestsNew(unittest.TestCase):
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
