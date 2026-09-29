import os
import sys
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

from backend.document import extract_text, truncate_preview
from backend.rag import (
    chunk_text,
    close_client,
)

# Detect whether chromadb is actually importable (it should be when the
# requirements are installed, but we degrade gracefully in CI / fresh
# venvs that haven't run pip install chromadb yet).
try:
    import chromadb  # noqa: F401
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False


class DocumentExtractionTests(unittest.TestCase):
    def test_extract_plain_text_txt(self):
        with NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello, world!")
            f.flush()
            result = extract_text(Path(f.name), "txt")
        self.assertEqual(result, "Hello, world!")

    def test_extract_plain_text_py(self):
        with NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def hello():\n    print('hi')")
            f.flush()
            result = extract_text(Path(f.name), "py")
        self.assertIn("def hello()", result)

    def test_extract_plain_text_md(self):
        with NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Title\n\nBody text")
            f.flush()
            result = extract_text(Path(f.name), "md")
        self.assertIn("Title", result)
        self.assertIn("Body text", result)

    def test_extract_plain_text_json(self):
        with NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"key": "value"}')
            f.flush()
            result = extract_text(Path(f.name), "json")
        self.assertIn("key", result)

    def test_extract_unknown_extension_returns_empty(self):
        with NamedTemporaryFile(mode="w", suffix=".xyz", delete=False) as f:
            f.write("random data")
            f.flush()
            result = extract_text(Path(f.name), "xyz")
        self.assertEqual(result, "")

    def test_extract_handles_missing_file_gracefully(self):
        result = extract_text(Path("/nonexistent/file.txt"), "txt")
        self.assertIn("Could not extract text", result)

    def test_extract_normalizes_extension_case(self):
        with NamedTemporaryFile(mode="w", suffix=".TXT", delete=False) as f:
            f.write("Case insensitive extension")
            f.flush()
            result = extract_text(Path(f.name), "TXT")
        self.assertEqual(result, "Case insensitive extension")


class TruncatePreviewTests(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual(truncate_preview("Hello"), "Hello")

    def test_long_text_truncated(self):
        text = "a" * 500
        result = truncate_preview(text, length=100)
        self.assertEqual(len(result), 101)  # 100 chars + …
        self.assertTrue(result.endswith("…"))

    def test_exact_length_not_truncated(self):
        text = "a" * 300
        result = truncate_preview(text, length=300)
        self.assertEqual(result, text)

    def test_empty_string_handled(self):
        self.assertEqual(truncate_preview(""), "")

    def test_whitespace_stripped(self):
        result = truncate_preview("  hello  ", length=300)
        self.assertEqual(result, "hello")


class ChunkingTests(unittest.TestCase):
    """Tests for the paragraph-aware overlapping chunker in rag.chunk_text()."""

    def test_chunk_text_small(self):
        """Text shorter than one chunk returns a single chunk."""
        text = "Hello world."
        chunks = chunk_text(text)
        self.assertIsInstance(chunks, list)
        self.assertEqual(len(chunks), 1)
        self.assertIn("Hello", chunks[0])

    def test_chunk_text_empty(self):
        """Empty string returns an empty list."""
        self.assertEqual(chunk_text(""), [])

    def test_chunk_text_whitespace(self):
        """Whitespace-only input returns an empty list."""
        self.assertEqual(chunk_text("   \n\n  "), [])

    def test_chunk_text_two_chunks(self):
        """Text that exceeds one chunk's char target produces two chunks."""
        # chunk_size=500 -> target_chars = 2000
        # Write 6000 chars -> should be at least 2 chunks
        text = "hello world " + ("a" * 5980)
        chunks = chunk_text(text)
        self.assertGreaterEqual(len(chunks), 2)

    def test_chunk_text_overlap(self):
        """Adjacent chunks share some text when overlap > 0."""
        # Use a long-ish paragraph so we definitely get multiple chunks.
        para = "The quick brown fox jumps over the lazy dog. " * 80
        chunks = chunk_text(para, chunk_size=50, overlap=10)
        if len(chunks) >= 2:
            # At least one word from the tail of chunk[0] should appear in chunk[1]
            tail_words = set(chunks[0].split()[-5:])
            head_words = set(chunks[1].split()[:5])
            self.assertTrue(
                tail_words & head_words,
                f"No overlap between:\n  {chunks[0][-100:]}\n  {chunks[1][:100]}",
            )

    def test_chunk_text_large_paragraph(self):
        """A single oversized paragraph is hard-split at the chunk boundary."""
        long_para = "hello world " + ("x" * 10000)
        chunks = chunk_text(long_para)
        self.assertGreaterEqual(len(chunks), 2)

    def test_chunk_text_exact_single(self):
        """Text just under the char target stays as one chunk."""
        # target_chars = 500 * 4 = 2000; use ~1500 chars to stay well under
        text = "hello world " * 100  # ~1200 chars, fits in one chunk
        chunks = chunk_text(text)
        self.assertEqual(len(chunks), 1)


@unittest.skipIf(not HAS_CHROMADB, "chromadb not installed — skipping RAG tests")
class RetrievalTests(unittest.TestCase):
    """Integration tests for index_document + retrieve_relevant_chunks."""

    _tmpdir: str | None = None

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["CHROMA_DB_PATH"] = cls._tmpdir.name
        # Force-import rag module module with the test path.
        # We need to reload rag so the CHROMA_DB_PATH env var takes effect.
        import importlib
        import backend.rag as rag_mod
        importlib.reload(rag_mod)
        global rag
        rag = rag_mod
        # Start with a clean index.
        rag.reset_vector_index()

    @classmethod
    def tearDownClass(cls):
        # Close the chromadb client to release the SQLite lock before cleanup.
        rag.close_client()
        if cls._tmpdir:
            cls._tmpdir.cleanup()
        if "CHROMA_DB_PATH" in os.environ:
            del os.environ["CHROMA_DB_PATH"]

    def setUp(self):
        # Ensure a clean collection before every test.
        try:
            rag.reset_vector_index()
        except Exception:
            pass

    def test_index_and_retrieve(self):
        """Index simple text and retrieve a relevant chunk."""
        rag.index_document("file1", "The sky is blue. Grass is green.", "test.txt")
        results = rag.retrieve_relevant_chunks("sky color", ["file1"], top_k=3)
        self.assertGreaterEqual(len(results), 1)
        # The retrieved text should contain something about the sky/blue
        combined = " ".join(r["text"] for r in results).lower()
        self.assertIn("sky", combined)
        self.assertIn("blue", combined)

    def test_retrieve_empty_query(self):
        """An empty query returns an empty list."""
        rag.index_document("file2", "Some content.", "doc.txt")
        results = rag.retrieve_relevant_chunks("", ["file2"])
        self.assertEqual(results, [])

    def test_retrieve_empty_file_ids(self):
        """Empty file_ids list returns an empty list."""
        rag.index_document("file3", "Some content.", "doc.txt")
        results = rag.retrieve_relevant_chunks("content", [])
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
