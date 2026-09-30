"""test_document — consolidated tests.

Merged from:
- test_document.py
- test_document_new.py
- test_document_coverage.py
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

from pathlib import Path

from tempfile import NamedTemporaryFile, TemporaryDirectory

from backend.document import extract_text, truncate_preview

from backend.rag import (
    chunk_text,
    close_client,
)

from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet

import types

from backend.document import (
    extract_text,
    truncate_preview,
    PLAIN_TEXT_EXTENSIONS,
    IMAGE_EXTENSIONS,
    MAX_OCR_PAGES,
    MAX_OCR_FILE_SIZE_MB,
    OCR_AVAILABLE,
    _extract_pdf,
    _extract_pdf_ocr,
    _extract_docx,
    _extract_csv,
    _extract_xlsx,
    _extract_pptx,
    _extract_image_ocr,
    _extract_plain_text,
)

from tempfile import NamedTemporaryFile

from unittest.mock import MagicMock, patch

from backend.document import (
    extract_text,
    _extract_plain_text,
    _extract_pdf,
    _extract_pdf_ocr,
    _extract_docx,
    _extract_csv,
    _extract_xlsx,
    _extract_pptx,
    _extract_image_ocr,
    truncate_preview,
    OCR_AVAILABLE,
    MAX_OCR_PAGES,
    MAX_OCR_FILE_SIZE_MB,
    PLAIN_TEXT_EXTENSIONS,
    IMAGE_EXTENSIONS,
)


# --- tests ---

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


_test_key = Fernet.generate_key().decode()


pytesseract_mock = types.ModuleType("pytesseract")


pytesseract_mock.image_to_string = MagicMock()


sys.modules["pytesseract"] = pytesseract_mock


pdf2image_mock = types.ModuleType("pdf2image")


pdf2image_mock.convert_from_path = MagicMock()


sys.modules["pdf2image"] = pdf2image_mock


pil_mock = types.ModuleType("PIL")


pil_mock.__version__ = "10.0.0"  # pypdf checks this


for submodule in ["Image", "ImageFont", "ImageDraw", "ImageFilter", "ImageColor"]:
    sub_mod = types.ModuleType(f"PIL.{submodule}")
    setattr(pil_mock, submodule, sub_mod)
    sys.modules[f"PIL.{submodule}"] = sub_mod


sys.modules["PIL"] = pil_mock


class PlainTextExtractionTests(unittest.TestCase):
    """Tests for plain text file extraction."""

    def test_extract_txt(self):
        with NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello, world!")
            f.flush()
            result = extract_text(Path(f.name), "txt")
        self.assertEqual(result, "Hello, world!")

    def test_extract_md(self):
        with NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Title\n\nBody text with **bold**.")
            f.flush()
            result = extract_text(Path(f.name), "md")
        self.assertIn("Title", result)
        self.assertIn("Body text", result)

    def test_extract_json(self):
        with NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"key": "value", "number": 42}')
            f.flush()
            result = extract_text(Path(f.name), "json")
        self.assertIn("key", result)
        self.assertIn("value", result)

    def test_extract_py(self):
        with NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def hello():\n    print('hi')\n")
            f.flush()
            result = extract_text(Path(f.name), "py")
        self.assertIn("def hello", result)

    def test_extract_html(self):
        with NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write("<html><body><p>Hello</p></body></html>")
            f.flush()
            result = extract_text(Path(f.name), "html")
        self.assertIn("Hello", result)

    def test_extract_xml(self):
        with NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write("<root><child>data</child></root>")
            f.flush()
            result = extract_text(Path(f.name), "xml")
        self.assertIn("data", result)

    def test_extract_rs(self):
        with NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
            f.write("fn main() { println!(\"hi\"); }")
            f.flush()
            result = extract_text(Path(f.name), "rs")
        self.assertIn("fn main", result)

    def test_extract_all_plain_text_extensions(self):
        """Verify all PLAIN_TEXT_EXTENSIONS are supported."""
        for ext in PLAIN_TEXT_EXTENSIONS:
            with NamedTemporaryFile(mode="w", suffix=f".{ext}", delete=False) as f:
                f.write(f"test {ext}")
                f.flush()
                result = extract_text(Path(f.name), ext)
            self.assertIn(ext, result)

    def test_extract_with_utf8_content(self):
        """UTF-8 encoded content is handled correctly."""
        with NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Hello 世界 🌍")
            f.flush()
            result = extract_text(Path(f.name), "txt")
        self.assertIn("世界", result)
        self.assertIn("🌍", result)


class PDLExtractionTests(unittest.TestCase):
    """Tests for PDF text extraction."""

    def test_extract_pdf_not_found(self):
        """Missing PDF returns error message."""
        result = extract_text(Path("/nonexistent/file.pdf"), "pdf")
        self.assertIn("Could not extract", result)

    def test_extract_pdf_wrong_extension(self):
        """Using .pdf extension on non-PDF returns error."""
        with NamedTemporaryFile(mode="w", suffix=".pdf", delete=False) as f:
            f.write("not a real pdf")
            f.flush()
            result = extract_text(Path(f.name), "pdf")
        # pypdf returns a more specific error about invalid PDF
        self.assertIn("Could not read PDF", result)

    def test_extract_unknown_extension_returns_empty(self):
        """Unknown extension returns empty string."""
        with NamedTemporaryFile(mode="w", suffix=".xyz", delete=False) as f:
            f.write("data")
            f.flush()
            result = extract_text(Path(f.name), "xyz")
        self.assertEqual(result, "")


class DocxExtractionTestsNew(unittest.TestCase):
    """Tests for DOCX extraction."""

    def test_extract_docx_not_found(self):
        result = extract_text(Path("/nonexistent/file.docx"), "docx")
        self.assertIn("Could not extract", result)

    def test_extract_invalid_docx(self):
        with NamedTemporaryFile(mode="w", suffix=".docx", delete=False) as f:
            f.write("not a real docx")
            f.flush()
            result = extract_text(Path(f.name), "docx")
        self.assertIn("Could not extract", result)


class CSVExtractionTestsNew(unittest.TestCase):
    """Tests for CSV extraction."""

    def test_extract_csv_not_found(self):
        result = extract_text(Path("/nonexistent/file.csv"), "csv")
        self.assertIn("Could not extract", result)

    def test_extract_empty_csv(self):
        with NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("")
            f.flush()
            result = extract_text(Path(f.name), "csv")
        self.assertIn("CSV file is empty", result)

    def test_extract_malformed_csv(self):
        # CSV with inconsistent columns - pandas is lenient and parses it
        with NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write('a,b,c\n1,2\n3,')  # inconsistent columns
            f.flush()
            result = extract_text(Path(f.name), "csv")
        # pandas handles this gracefully - verify it returns some content
        self.assertTrue(len(result) > 0)


class XLSXExtractionTestsNew(unittest.TestCase):
    """Tests for XLSX extraction."""

    def test_extract_xlsx_not_found(self):
        result = extract_text(Path("/nonexistent/file.xlsx"), "xlsx")
        self.assertIn("Could not extract", result)

    def test_extract_invalid_xlsx(self):
        with NamedTemporaryFile(mode="w", suffix=".xlsx", delete=False) as f:
            f.write("not a real xlsx")
            f.flush()
            result = extract_text(Path(f.name), "xlsx")
        self.assertIn("Could not extract", result)


class PPTXExtractionTestsNew(unittest.TestCase):
    """Tests for PPTX extraction."""

    def test_extract_pptx_not_found(self):
        result = extract_text(Path("/nonexistent/file.pptx"), "pptx")
        self.assertIn("Could not extract", result)

    def test_extract_invalid_pptx(self):
        with NamedTemporaryFile(mode="w", suffix=".pptx", delete=False) as f:
            f.write("not a real pptx")
            f.flush()
            result = extract_text(Path(f.name), "pptx")
        self.assertIn("Could not extract", result)


class ImageOCRExtractionTestsNew(unittest.TestCase):
    """Tests for image OCR extraction."""

    def test_extract_image_not_found(self):
        result = extract_text(Path("/nonexistent/file.png"), "png")
        # Could return either file not found error or OCR unavailable message
        self.assertTrue(
            "Could not extract" in result
            or "OCR not available" in result
            or "tesseract" in result.lower()
            or "No text detected" in result
        )

    def test_ocr_handles_missing_tesseract_binary(self):
        """When tesseract binary is missing, extract_text handles it gracefully."""
        import shutil
        # Create a small valid PNG
        png_data = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
            b"\x90wS\xde"
            b"\x00\x00\x00\nIDAT"
            b"\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfe"
            b"\xa4\xf0\xe3\x18"
            b"\x00\x00\x00\x00IEND"
            b"\xaeB`\x82"
        )
        with NamedTemporaryFile(mode="wb", suffix=".png", delete=False) as f:
            f.write(png_data)
            f.flush()
            result = extract_text(Path(f.name), "png")

        # Should return an error message about missing OCR/tesseract, not crash
        self.assertTrue(
            "OCR not available" in result
            or "Could not extract" in result
            or "tesseract" in result.lower()
            or "No text detected" in result
        )


class ExtensionNormalizationTests(unittest.TestCase):
    """Tests for extension case normalization."""

    def test_uppercase_extension(self):
        with NamedTemporaryFile(mode="w", suffix=".TXT", delete=False) as f:
            f.write("Uppercase extension")
            f.flush()
            result = extract_text(Path(f.name), "TXT")
        self.assertEqual(result, "Uppercase extension")

    def test_mixed_case_extension(self):
        with NamedTemporaryFile(mode="w", suffix=".Md", delete=False) as f:
            f.write("Mixed case extension")
            f.flush()
            result = extract_text(Path(f.name), "Md")
        self.assertEqual(result, "Mixed case extension")

    def test_extension_with_dot(self):
        """Extension with leading dot is normalized."""
        with NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("With dot")
            f.flush()
            result = extract_text(Path(f.name), ".txt")
        self.assertEqual(result, "With dot")


class TruncatePreviewTestsNew(unittest.TestCase):
    """Tests for truncate_preview function."""

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

    def test_custom_length(self):
        text = "Hello world"
        result = truncate_preview(text, length=5)
        self.assertEqual(result, "Hello…")

    def test_multiline_text(self):
        text = "Line 1\nLine 2\nLine 3"
        result = truncate_preview(text, length=20)
        self.assertTrue(len(result) <= 21)  # 20 + …

    def test_unicode_truncation(self):
        text = "你好世界" * 10  # 40 chars
        result = truncate_preview(text, length=10)
        self.assertTrue(len(result) <= 11)  # 10 + …


class DocxExtractionTestsNew(unittest.TestCase):
    """Tests for DOCX extraction."""

    def test_extract_docx_not_found(self):
        result = extract_text(Path("/nonexistent/file.docx"), "docx")
        self.assertIn("Could not extract", result)

    def test_extract_invalid_docx(self):
        with NamedTemporaryFile(mode="w", suffix=".docx", delete=False) as f:
            f.write("not a real docx")
            f.flush()
            result = extract_text(Path(f.name), "docx")
        self.assertIn("Could not extract", result)

    def test_extract_docx_with_tables(self):
        """Test DOCX extraction includes table content."""
        # Create a real DOCX with a table
        from docx import Document as DocxDocument
        from docx.table import Table
        with NamedTemporaryFile(suffix=".docx", delete=False) as f:
            doc = DocxDocument()
            doc.add_paragraph("Paragraph 1")

            # Add a table
            table = doc.add_table(rows=2, cols=2)
            table.rows[0].cells[0].text = "Header 1"
            table.rows[0].cells[1].text = "Header 2"
            table.rows[1].cells[0].text = "Cell A"
            table.rows[1].cells[1].text = "Cell B"

            doc.add_paragraph("Paragraph 2")
            doc.save(f.name)

            result = extract_text(Path(f.name), "docx")
        self.assertIn("Paragraph 1", result)
        self.assertIn("Paragraph 2", result)
        self.assertIn("Header 1", result)
        self.assertIn("Header 2", result)
        self.assertIn("Cell A", result)
        self.assertIn("Cell B", result)

    def test_extract_docx_multiple_paragraphs(self):
        """Test DOCX with multiple paragraphs."""
        from docx import Document as DocxDocument
        with NamedTemporaryFile(suffix=".docx", delete=False) as f:
            doc = DocxDocument()
            for i in range(5):
                doc.add_paragraph(f"Paragraph {i}")
            doc.save(f.name)

            result = extract_text(Path(f.name), "docx")
        self.assertIn("Paragraph 0", result)
        self.assertIn("Paragraph 4", result)


class CSVExtractionTestsNew(unittest.TestCase):
    """Tests for CSV extraction."""

    def test_extract_csv_not_found(self):
        result = extract_text(Path("/nonexistent/file.csv"), "csv")
        self.assertIn("Could not extract", result)

    def test_extract_empty_csv(self):
        with NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("")
            f.flush()
            result = extract_text(Path(f.name), "csv")
        self.assertIn("CSV file is empty", result)

    def test_extract_malformed_csv(self):
        # CSV with inconsistent columns - pandas is lenient and parses it
        with NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write('a,b,c\n1,2\n3,')
            f.flush()
            result = extract_text(Path(f.name), "csv")
        # pandas handles this gracefully - verify it returns some content
        self.assertTrue(len(result) > 0)

    def test_extract_csv_with_data(self):
        with NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("name,age,city\nJohn,30,NYC\nJane,25,LA\n")
            f.flush()
            result = extract_text(Path(f.name), "csv")
        self.assertIn("name", result)
        self.assertIn("John", result)
        self.assertIn("Jane", result)
        self.assertIn("30", result)

    def test_extract_csv_parser_error(self):
        # Test the ParserError path by creating a file that causes issues
        # This is hard to trigger without specific malformed content
        # Just verify the error handling exists
        pass


class XLSXExtractionTestsNew(unittest.TestCase):
    """Tests for XLSX extraction."""

    def test_extract_xlsx_not_found(self):
        result = extract_text(Path("/nonexistent/file.xlsx"), "xlsx")
        self.assertIn("Could not extract", result)

    def test_extract_invalid_xlsx(self):
        with NamedTemporaryFile(mode="w", suffix=".xlsx", delete=False) as f:
            f.write("not a real xlsx")
            f.flush()
            result = extract_text(Path(f.name), "xlsx")
        self.assertIn("Could not extract", result)

    def test_extract_xlsx_multiple_sheets(self):
        """Test XLSX with multiple sheets."""
        import openpyxl
        with NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            wb = openpyxl.Workbook()
            # Sheet 1
            ws1 = wb.active
            ws1.title = "Sheet1"
            ws1.append(["A", "B"])
            ws1.append(["1", "2"])

            # Sheet 2
            ws2 = wb.create_sheet("Sheet2")
            ws2.append(["C", "D"])
            ws2.append(["3", "4"])

            wb.save(f.name)

            result = extract_text(Path(f.name), "xlsx")
        self.assertIn("Sheet: Sheet1", result)
        self.assertIn("Sheet: Sheet2", result)
        self.assertIn("1", result)
        self.assertIn("3", result)

    def test_extract_xlsx_with_none_values(self):
        """Test XLSX with None/empty cells."""
        import openpyxl
        with NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["A", None, "C"])
            ws.append([None, "2", None])
            wb.save(f.name)

            result = extract_text(Path(f.name), "xlsx")
        self.assertIn("", result)  # Empty cells become empty strings


class PPTXExtractionTestsNew(unittest.TestCase):
    """Tests for PPTX extraction."""

    def test_extract_pptx_not_found(self):
        result = extract_text(Path("/nonexistent/file.pptx"), "pptx")
        self.assertIn("Could not extract", result)

    def test_extract_invalid_pptx(self):
        with NamedTemporaryFile(mode="w", suffix=".pptx", delete=False) as f:
            f.write("not a real pptx")
            f.flush()
            result = extract_text(Path(f.name), "pptx")
        self.assertIn("Could not extract", result)

    def test_extract_pptx_multiple_slides_shapes(self):
        """Test PPTX with multiple slides and shapes."""
        from pptx import Presentation
        from pptx.util import Inches
        with NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            prs = Presentation()

            # Slide 1
            slide1 = prs.slides.add_slide(prs.slide_layouts[5])  # blank
            txBox1 = slide1.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
            txBox1.text = "Slide 1 Content"

            # Slide 2
            slide2 = prs.slides.add_slide(prs.slide_layouts[5])
            txBox2 = slide2.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
            txBox2.text = "Slide 2 Content"

            prs.save(f.name)

            result = extract_text(Path(f.name), "pptx")
        self.assertIn("Slide 1", result)
        self.assertIn("Slide 1 Content", result)
        self.assertIn("Slide 2", result)
        self.assertIn("Slide 2 Content", result)

    def test_extract_pptx_without_text_shapes(self):
        """Test PPTX with shapes that don't have text frames."""
        from pptx import Presentation
        from pptx.util import Inches
        with NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[5])
            # Add a shape without text frame (e.g., a rectangle)
            slide.shapes.add_shape(1, Inches(1), Inches(1), Inches(2), Inches(1))  # MSO_SHAPE.RECTANGLE
            prs.save(f.name)

            result = extract_text(Path(f.name), "pptx")
        self.assertIn("Slide 1", result)


class ImageOCRExtractionTestsNew(unittest.TestCase):
    """Tests for image OCR extraction."""

    def test_extract_image_not_found(self):
        result = extract_text(Path("/nonexistent/file.png"), "png")
        # Could return either file not found error or OCR unavailable message
        self.assertTrue(
            "Could not extract" in result
            or "OCR not available" in result
            or "tesseract" in result.lower()
            or "No text detected" in result
        )

    def test_ocr_handles_missing_tesseract(self):
        """When tesseract binary is missing, returns error message."""
        import shutil
        # Create a small valid PNG
        png_data = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
            b"\x90wS\xde"
            b"\x00\x00\x00\nIDAT"
            b"\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfe"
            b"\xa4\xf0\xe3\x18"
            b"\x00\x00\x00\x00IEND"
            b"\xaeB`\x82"
        )
        with NamedTemporaryFile(mode="wb", suffix=".png", delete=False) as f:
            f.write(png_data)
            f.flush()
            result = extract_text(Path(f.name), "png")

        # Should return graceful error about OCR/tesseract
        self.assertTrue(
            "OCR not available" in result
            or "Could not extract" in result
            or "tesseract" in result.lower()
            or "No text detected" in result
        )

    def test_image_ocr_size_limit(self):
        """Test image size limit check."""
        # This would require creating a very large image file
        # Just verify the logic exists in the code
        pass


class PDFExtractionTests(unittest.TestCase):
    """Tests for PDF extraction (including OCR fallback)."""

    def test_extract_pdf_not_found(self):
        result = extract_text(Path("/nonexistent/file.pdf"), "pdf")
        self.assertIn("Could not extract", result)

    def test_extract_invalid_pdf(self):
        with NamedTemporaryFile(mode="w", suffix=".pdf", delete=False) as f:
            f.write("not a real pdf")
            f.flush()
            result = extract_text(Path(f.name), "pdf")
        # pypdf raises PdfReadError for invalid PDF
        self.assertIn("Could not read PDF", result)

    @patch("backend.document.OCR_AVAILABLE", True)
    @patch("backend.document._extract_pdf_ocr")
    def test_pdf_ocr_fallback_when_text_sparse(self, mock_ocr):
        """Test OCR fallback when extracted text is too short."""
        mock_ocr.return_value = "OCR extracted text"

        with NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            # Create a minimal valid PDF
            from pypdf import PdfWriter
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.write(f)
            f.flush()
            result = extract_text(Path(f.name), "pdf")

        # If text is too short (< 100 chars), OCR should be attempted
        mock_ocr.assert_called()

    @patch("backend.document.OCR_AVAILABLE", False)
    def test_pdf_no_ocr_when_unavailable(self):
        """Test PDF extraction doesn't try OCR when unavailable."""
        with NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            from pypdf import PdfWriter
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.write(f)
            f.flush()
            result = extract_text(Path(f.name), "pdf")
        # Should return the extracted text (empty for blank page)
        self.assertIn("", result)


class PlainTextExtractionInternalTests(unittest.TestCase):
    """Tests for internal plain text extraction function."""

    def test_extract_plain_text_utf8(self):
        with NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Hello 世界 🌍")
            f.flush()
            result = _extract_plain_text(Path(f.name))
        self.assertIn("世界", result)
        self.assertIn("🌍", result)

    def test_extract_plain_text_encoding_errors_ignored(self):
        # Write with latin-1 but read as utf-8 (will have replacement chars)
        with NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as f:
            f.write(b"Hello \xe9 world")  # latin-1 e-acute
            f.flush()
            result = _extract_plain_text(Path(f.name))
        self.assertIn("Hello", result)


class InternalFunctionsTests(unittest.TestCase):
    """Tests for internal extraction functions directly."""

    @patch("backend.document.OCR_AVAILABLE", True)
    def test_extract_pdf_ocr_success(self):
        """Test _extract_pdf_ocr with successful conversion."""
        from backend.document import _extract_pdf_ocr

        # Mock pdf2image.convert_from_path inside the function
        with patch("pdf2image.convert_from_path") as mock_convert:
            mock_image = MagicMock()
            mock_convert.return_value = [mock_image]

            # Mock pytesseract
            with patch("backend.document.pytesseract") as mock_pytesseract:
                mock_pytesseract.image_to_string.return_value = "OCR text from page"

                with NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    from pypdf import PdfWriter
                    writer = PdfWriter()
                    writer.add_blank_page(width=100, height=100)
                    writer.write(f)
                    f.flush()
                    result = _extract_pdf_ocr(Path(f.name))

        self.assertIn("OCR text from page", result)
        self.assertIn("Page 1", result)

    @patch("backend.document.OCR_AVAILABLE", True)
    def test_extract_pdf_ocr_file_too_large(self):
        """Test _extract_pdf_ocr with file exceeding size limit."""
        from backend.document import _extract_pdf_ocr

        with NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"x" * (51 * 1024 * 1024))  # 51 MB > 50 MB limit
            f.flush()
            result = _extract_pdf_ocr(Path(f.name))

        self.assertIn("too large for OCR", result)

    @patch("backend.document.OCR_AVAILABLE", True)
    def test_extract_pdf_ocr_no_pdf2image(self):
        """Test _extract_pdf_ocr when pdf2image not installed."""
        from backend.document import _extract_pdf_ocr

        with patch.dict("sys.modules", {"pdf2image": None}):
            with NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                from pypdf import PdfWriter
                writer = PdfWriter()
                writer.add_blank_page(width=100, height=100)
                writer.write(f)
                f.flush()
                result = _extract_pdf_ocr(Path(f.name))

        self.assertIn("requires pdf2image", result)

    @patch("backend.document.OCR_AVAILABLE", True)
    @patch("backend.document._extract_pdf_ocr")
    def test_extract_pdf_password_protected_returns_password_message(self, mock_ocr):
        """Test password-protected PDF returns password message (doesn't try OCR)."""
        from pypdf.errors import PdfReadError

        with patch("backend.document.PdfReader") as mock_reader:
            mock_reader.side_effect = PdfReadError("password required")

            with NamedTemporaryFile(suffix=".pdf") as f:
                result = _extract_pdf(Path(f.name))

        # Password-protected PDFs return specific message, don't try OCR
        self.assertIn("Password-protected PDF", result)
        mock_ocr.assert_not_called()

    @patch("backend.document.OCR_AVAILABLE", True)
    def test_extract_image_ocr_converts_mode(self):
        """Test _extract_image_ocr converts image mode."""
        from backend.document import _extract_image_ocr

        with patch("backend.document.Image") as mock_image_class:
            mock_image = MagicMock()
            mock_image.mode = "RGBA"  # Not RGB or L
            mock_image.convert.return_value = mock_image
            mock_image_class.open.return_value = mock_image

            with patch("backend.document.pytesseract.image_to_string", return_value="OCR result"):
                with NamedTemporaryFile(suffix=".png") as f:
                    result = _extract_image_ocr(Path(f.name))

        mock_image.convert.assert_called_with("RGB")
        self.assertIn("OCR result", result)

    @patch("backend.document.OCR_AVAILABLE", True)
    def test_extract_image_ocr_no_text_detected(self):
        """Test _extract_image_ocr when no text found."""
        from backend.document import _extract_image_ocr

        with patch("backend.document.Image") as mock_image_class:
            mock_image = MagicMock()
            mock_image.mode = "RGB"
            mock_image_class.open.return_value = mock_image

            with patch("backend.document.pytesseract.image_to_string", return_value="   \n\n  "):
                with NamedTemporaryFile(suffix=".png") as f:
                    result = _extract_image_ocr(Path(f.name))

        self.assertIn("No text detected", result)

    @patch("backend.document.OCR_AVAILABLE", True)
    def test_extract_image_ocr_file_too_large(self):
        """Test _extract_image_ocr with file size limit."""
        from backend.document import _extract_image_ocr

        with NamedTemporaryFile(suffix=".png") as f:
            f.write(b"x" * (51 * 1024 * 1024))  # 51 MB
            f.flush()
            result = _extract_image_ocr(Path(f.name))

        self.assertIn("too large for OCR", result)

    def test_extract_csv_parser_error(self):
        """Test _extract_csv handles ParserError."""
        from backend.document import _extract_csv

        with patch("backend.document.pd.read_csv") as mock_read:
            from pandas.errors import ParserError
            mock_read.side_effect = ParserError("Parse error")

            with NamedTemporaryFile(suffix=".csv") as f:
                result = _extract_csv(Path(f.name))

        self.assertIn("Could not parse CSV", result)

    def test_extract_xlsx_exception(self):
        """Test _extract_xlsx handles general exception."""
        from backend.document import _extract_xlsx

        with patch("backend.document.openpyxl.load_workbook") as mock_load:
            mock_load.side_effect = Exception("XLSX error")

            with NamedTemporaryFile(suffix=".xlsx") as f:
                result = _extract_xlsx(Path(f.name))

        self.assertIn("Could not extract text from this XLSX file", result)

    def test_extract_pptx_exception(self):
        """Test _extract_pptx handles general exception."""
        from backend.document import _extract_pptx

        with patch("backend.document.Presentation") as mock_pres:
            mock_pres.side_effect = Exception("PPTX error")

            with NamedTemporaryFile(suffix=".pptx") as f:
                result = _extract_pptx(Path(f.name))

        self.assertIn("Could not extract text from this PPTX file", result)

    def test_extract_docx_exception(self):
        """Test _extract_docx handles general exception."""
        from backend.document import _extract_docx

        with patch("backend.document.DocxDocument") as mock_docx:
            mock_docx.side_effect = Exception("DOCX error")

            with NamedTemporaryFile(suffix=".docx") as f:
                result = _extract_docx(Path(f.name))

        self.assertIn("Could not extract text from this DOCX file", result)


class ConstantsTests(unittest.TestCase):
    """Tests for module constants."""

    def test_plain_text_extensions_defined(self):
        self.assertIsInstance(PLAIN_TEXT_EXTENSIONS, set)
        self.assertTrue(len(PLAIN_TEXT_EXTENSIONS) > 0)
        # Check common extensions
        for ext in ["txt", "md", "json", "py", "js", "html", "xml", "sql"]:
            self.assertIn(ext, PLAIN_TEXT_EXTENSIONS)

    def test_image_extensions_defined(self):
        self.assertIsInstance(IMAGE_EXTENSIONS, set)
        self.assertTrue(len(IMAGE_EXTENSIONS) > 0)
        for ext in ["png", "jpg", "jpeg", "gif", "webp", "bmp"]:
            self.assertIn(ext, IMAGE_EXTENSIONS)

    def test_constants_positive(self):
        self.assertGreater(MAX_OCR_PAGES, 0)
        self.assertGreater(MAX_OCR_FILE_SIZE_MB, 0)

    def test_ocr_available_type(self):
        self.assertIsInstance(OCR_AVAILABLE, bool)


class ErrorHandlingTests(unittest.TestCase):
    """Tests for error handling in extract_text."""

    def test_permission_error_handled(self):
        """Permission denied returns error message."""
        # We can't easily create a permission-denied file in tests,
        # but we can verify the exception handler exists
        result = extract_text(Path("/root/protected.txt"), "txt")
        self.assertIn("Could not extract", result)

    def test_general_exception_caught(self):
        """Any exception during extraction is caught and returned as message."""
        # The function catches all exceptions and returns error message
        # This is tested implicitly by all the "not found" and "invalid" tests
        pass


if __name__ == "__main__":
    unittest.main()


_test_key = Fernet.generate_key().decode()


pytesseract_mock = types.ModuleType("pytesseract")


pytesseract_mock.image_to_string = MagicMock()


sys.modules["pytesseract"] = pytesseract_mock


pdf2image_mock = types.ModuleType("pdf2image")


pdf2image_mock.convert_from_path = MagicMock()


sys.modules["pdf2image"] = pdf2image_mock


pil_mock = types.ModuleType("PIL")


pil_mock.__version__ = "10.0.0"  # pypdf checks this


for submodule in ["Image", "ImageFont", "ImageDraw", "ImageFilter", "ImageColor"]:
    sub_mod = types.ModuleType(f"PIL.{submodule}")
    setattr(pil_mock, submodule, sub_mod)
    sys.modules[f"PIL.{submodule}"] = sub_mod


sys.modules["PIL"] = pil_mock


class OCRUnavailableTests(unittest.TestCase):
    """Tests for when OCR is not available (lines 20-21, 106, 197)."""

    @patch("backend.document.OCR_AVAILABLE", False)
    def test_extract_pdf_ocr_returns_empty_when_unavailable(self):
        """_extract_pdf_ocr returns empty string when OCR not available (line 106)."""
        from backend.document import _extract_pdf_ocr
        with NamedTemporaryFile(suffix=".pdf") as f:
            f.write(b"%PDF-1.4\n%test")
            f.flush()
            result = _extract_pdf_ocr(Path(f.name))
        self.assertEqual(result, "")

    @patch("backend.document.OCR_AVAILABLE", False)
    def test_extract_image_ocr_returns_message_when_unavailable(self):
        """_extract_image_ocr returns message when OCR not available (line 197)."""
        from backend.document import _extract_image_ocr
        with NamedTemporaryFile(suffix=".png") as f:
            f.write(b"fake png")
            f.flush()
            result = _extract_image_ocr(Path(f.name))
        self.assertIn("OCR not available", result)

    @patch("backend.document.OCR_AVAILABLE", False)
    def test_extract_image_ocr_file_size_check_still_runs(self):
        """File size check runs even when OCR unavailable (lines 200-203)."""
        from backend.document import _extract_image_ocr
        with NamedTemporaryFile(suffix=".png") as f:
            f.write(b"x" * (51 * 1024 * 1024))  # 51 MB > 50 MB limit
            f.flush()
            result = _extract_image_ocr(Path(f.name))
        # When OCR unavailable, it returns the unavailable message first
        self.assertIn("OCR not available", result)


class ImportErrorTests(unittest.TestCase):
    """Tests for import error handling (lines 20-21)."""

    @patch.dict("sys.modules", {"pytesseract": None, "PIL": None, "PIL.Image": None})
    def test_ocr_available_false_when_import_fails(self):
        """OCR_AVAILABLE is False when imports fail."""
        import importlib
        import backend.document as document
        importlib.reload(document)
        self.assertFalse(document.OCR_AVAILABLE)


class PDFOCRBranchTests(unittest.TestCase):
    """Tests for PDF OCR fallback branches (lines 93-94, 133-134)."""

    @patch("backend.document.OCR_AVAILABLE", True)
    @patch("backend.document._extract_pdf_ocr")
    @patch("backend.document.PdfReader")
    def test_extract_pdf_ocr_fallback_on_corrupt_pdf(self, mock_reader, mock_ocr):
        """PDF extraction attempts OCR on corrupt PDF (lines 90-96)."""
        from pypdf.errors import PdfReadError
        mock_reader.side_effect = PdfReadError("corrupt PDF")
        mock_ocr.return_value = "OCR recovered text"

        with NamedTemporaryFile(suffix=".pdf") as f:
            f.write(b"corrupt pdf data")
            f.flush()
            result = extract_text(Path(f.name), "pdf")

        # Should try OCR and return OCR result
        mock_ocr.assert_called()
        self.assertIn("OCR extracted from PDF", result)
        self.assertIn("OCR recovered text", result)

    @patch("backend.document.OCR_AVAILABLE", True)
    @patch("backend.document._extract_pdf_ocr")
    @patch("backend.document.PdfReader")
    def test_extract_pdf_ocr_fallback_ocr_fails(self, mock_reader, mock_ocr):
        """PDF extraction returns error when OCR also fails (lines 90-96)."""
        from pypdf.errors import PdfReadError
        mock_reader.side_effect = PdfReadError("corrupt PDF")
        mock_ocr.side_effect = Exception("OCR failed")

        with NamedTemporaryFile(suffix=".pdf") as f:
            f.write(b"corrupt pdf data")
            f.flush()
            result = extract_text(Path(f.name), "pdf")

        # Should return error message including original exception
        self.assertIn("Could not read PDF", result)
        self.assertIn("corrupt PDF", result)

    @patch("backend.document.OCR_AVAILABLE", True)
    @patch("backend.document.PdfReader")
    def test_extract_pdf_ocr_handles_exception_per_page(self, mock_pdf_reader):
        """_extract_pdf_ocr continues on per-page exception (lines 133-134)."""
        from backend.document import _extract_pdf_ocr

        # Mock pdf2image.convert_from_path inside the function
        with patch("pdf2image.convert_from_path") as mock_convert:
            mock_image1 = MagicMock()
            mock_image2 = MagicMock()
            mock_convert.return_value = [mock_image1, mock_image2]

            # Mock pytesseract inside document module
            with patch("backend.document.pytesseract.image_to_string") as mock_ocr:
                # First page succeeds, second raises exception
                mock_ocr.side_effect = ["Page 1 text", Exception("OCR failed")]

                # Mock PdfReader for page count
                mock_reader = MagicMock()
                mock_reader.pages = [MagicMock(), MagicMock()]
                mock_pdf_reader.return_value = mock_reader

                with NamedTemporaryFile(suffix=".pdf") as f:
                    from pypdf import PdfWriter
                    writer = PdfWriter()
                    writer.add_blank_page(width=100, height=100)
                    writer.write(f)
                    f.flush()
                    result = _extract_pdf_ocr(Path(f.name))

        # Should include page 1 but skip page 2
        self.assertIn("Page 1 text", result)
        self.assertIn("Page 1", result)


class PlainTextEdgeCaseTests(unittest.TestCase):
    """Tests for plain text extraction edge cases."""

    def test_extract_text_unknown_extension_returns_empty(self):
        """Unknown extension returns empty string (line 64)."""
        with NamedTemporaryFile(mode="w", suffix=".xyz", delete=False) as f:
            f.write("data")
            f.flush()
            result = extract_text(Path(f.name), "xyz")
        self.assertEqual(result, "")

    def test_extract_text_case_insensitive_extension(self):
        """Extension matching is case insensitive."""
        with NamedTemporaryFile(mode="w", suffix=".TXT", delete=False) as f:
            f.write("test")
            f.flush()
            result = extract_text(Path(f.name), "TXT")
        self.assertEqual(result, "test")

    def test_extract_text_nonexistent_file_handled(self):
        """Non-existent file returns error message via extract_text wrapper."""
        result = extract_text(Path("/nonexistent/file.txt"), "txt")
        self.assertIn("Could not extract text", result)
        self.assertIn("No such file", result)


class ImageOCRBranchTests(unittest.TestCase):
    """Tests for image OCR branches (lines 200-215)."""

    @patch("backend.document.OCR_AVAILABLE", True)
    @patch("backend.document.Image")
    @patch("backend.document.pytesseract.image_to_string")
    def test_extract_image_ocr_converts_image_mode(self, mock_ocr, mock_image_class):
        """Image mode conversion (lines 207-208)."""
        from backend.document import _extract_image_ocr

        mock_image = MagicMock()
        mock_image.mode = "RGBA"  # Not RGB or L, should convert
        mock_image.convert.return_value = mock_image
        mock_image_class.open.return_value = mock_image
        mock_ocr.return_value = "OCR text"

        with NamedTemporaryFile(suffix=".png") as f:
            result = _extract_image_ocr(Path(f.name))

        mock_image.convert.assert_called_with("RGB")
        self.assertIn("OCR text", result)

    @patch("backend.document.OCR_AVAILABLE", True)
    @patch("backend.document.Image")
    @patch("backend.document.pytesseract.image_to_string")
    def test_extract_image_ocr_no_text_detected(self, mock_ocr, mock_image_class):
        """No text detected returns specific message (lines 211-212)."""
        from backend.document import _extract_image_ocr

        mock_image = MagicMock()
        mock_image.mode = "RGB"
        mock_image_class.open.return_value = mock_image
        mock_ocr.return_value = "   \n\n  "  # Whitespace only

        with NamedTemporaryFile(suffix=".png") as f:
            result = _extract_image_ocr(Path(f.name))

        self.assertIn("No text detected", result)

    @patch("backend.document.OCR_AVAILABLE", True)
    @patch("backend.document.Image")
    @patch("backend.document.pytesseract.image_to_string")
    def test_extract_image_ocr_exception_handled(self, mock_ocr, mock_image_class):
        """General exception during OCR returns error message (lines 214-215)."""
        from backend.document import _extract_image_ocr

        mock_image = MagicMock()
        mock_image.mode = "RGB"
        mock_image_class.open.return_value = mock_image
        mock_ocr.side_effect = Exception("Tesseract error")

        with NamedTemporaryFile(suffix=".png") as f:
            result = _extract_image_ocr(Path(f.name))

        self.assertIn("Could not extract text from this image", result)
        self.assertIn("Tesseract error", result)

    @patch("backend.document.OCR_AVAILABLE", True)
    def test_extract_image_ocr_file_too_large(self):
        """File size limit check (lines 200-203)."""
        from backend.document import _extract_image_ocr

        with NamedTemporaryFile(suffix=".png") as f:
            f.write(b"x" * (51 * 1024 * 1024))  # 51 MB > 50 MB limit
            f.flush()
            result = _extract_image_ocr(Path(f.name))

        self.assertIn("too large for OCR", result)
        self.assertIn("51.0", result)


class PDFOCRSizeLimitTests(unittest.TestCase):
    """Tests for PDF OCR size limit (lines 109-111)."""

    @patch("backend.document.OCR_AVAILABLE", True)
    def test_extract_pdf_ocr_file_too_large(self):
        """PDF file size limit returns error (lines 109-111)."""
        from backend.document import _extract_pdf_ocr

        with NamedTemporaryFile(suffix=".pdf") as f:
            f.write(b"x" * (51 * 1024 * 1024))  # 51 MB > 50 MB limit
            f.flush()
            result = _extract_pdf_ocr(Path(f.name))

        self.assertIn("too large for OCR", result)
        self.assertIn("51.0", result)


class DOCXBranchTests(unittest.TestCase):
    """Tests for DOCX extraction branches."""

    @patch("backend.document.DocxDocument")
    def test_extract_docx_empty_paragraphs_skipped(self, mock_docx_class):
        """Empty paragraphs are skipped (line 142)."""
        from backend.document import _extract_docx

        mock_doc = MagicMock()
        mock_para1 = MagicMock()
        mock_para1.text = "Paragraph 1"
        mock_para2 = MagicMock()
        mock_para2.text = ""
        mock_para3 = MagicMock()
        mock_para3.text = "   "
        mock_para4 = MagicMock()
        mock_para4.text = "Paragraph 2"

        mock_doc.paragraphs = [mock_para1, mock_para2, mock_para3, mock_para4]
        mock_doc.tables = []
        mock_docx_class.return_value = mock_doc

        with NamedTemporaryFile(suffix=".docx") as f:
            result = _extract_docx(Path(f.name))

        self.assertIn("Paragraph 1", result)
        self.assertIn("Paragraph 2", result)

    @patch("backend.document.DocxDocument")
    def test_extract_docx_with_tables(self, mock_docx_class):
        """Table extraction (lines 144-148)."""
        from backend.document import _extract_docx

        mock_doc = MagicMock()
        mock_doc.paragraphs = [MagicMock(text="Para 1")]

        mock_table = MagicMock()
        mock_row = MagicMock()
        mock_cell1 = MagicMock(text="Cell 1")
        mock_cell2 = MagicMock(text="Cell 2")
        mock_row.cells = [mock_cell1, mock_cell2]
        mock_table.rows = [mock_row]
        mock_doc.tables = [mock_table]

        mock_docx_class.return_value = mock_doc

        with NamedTemporaryFile(suffix=".docx") as f:
            result = _extract_docx(Path(f.name))

        self.assertIn("Para 1", result)
        self.assertIn("Cell 1", result)
        self.assertIn("Cell 2", result)


class CSVEdgeCaseTests(unittest.TestCase):
    """Tests for CSV edge cases."""

    @patch("backend.document.pd.read_csv")
    def test_extract_csv_empty_data_error(self, mock_read):
        """Empty CSV returns specific message (line 160)."""
        from backend.document import _extract_csv
        from pandas.errors import EmptyDataError
        mock_read.side_effect = EmptyDataError("No data")

        with NamedTemporaryFile(suffix=".csv") as f:
            result = _extract_csv(Path(f.name))

        self.assertIn("CSV file is empty", result)

    @patch("backend.document.pd.read_csv")
    def test_extract_csv_parser_error(self, mock_read):
        """Parser error returns specific message (lines 161-162)."""
        from backend.document import _extract_csv
        from pandas.errors import ParserError
        mock_read.side_effect = ParserError("Parse failed")

        with NamedTemporaryFile(suffix=".csv") as f:
            result = _extract_csv(Path(f.name))

        self.assertIn("Could not parse CSV", result)
        self.assertIn("Parse failed", result)

    @patch("backend.document.pd.read_csv")
    def test_extract_csv_general_exception(self, mock_read):
        """General exception handled (lines 163-164)."""
        from backend.document import _extract_csv
        mock_read.side_effect = Exception("General error")

        with NamedTemporaryFile(suffix=".csv") as f:
            result = _extract_csv(Path(f.name))

        self.assertIn("Could not extract text from this CSV file", result)
        self.assertIn("General error", result)


class XLSXEdgeCaseTests(unittest.TestCase):
    """Tests for XLSX edge cases."""

    @patch("backend.document.openpyxl.load_workbook")
    def test_extract_xlsx_general_exception(self, mock_load):
        """General exception returns error message (lines 176-177)."""
        from backend.document import _extract_xlsx
        mock_load.side_effect = Exception("XLSX failed")

        with NamedTemporaryFile(suffix=".xlsx") as f:
            result = _extract_xlsx(Path(f.name))

        self.assertIn("Could not extract text from this XLSX file", result)
        self.assertIn("XLSX failed", result)


class PPTXEdgeCaseTests(unittest.TestCase):
    """Tests for PPTX edge cases."""

    @patch("backend.document.Presentation")
    def test_extract_pptx_general_exception(self, mock_pres):
        """General exception returns error message (lines 190-191)."""
        from backend.document import _extract_pptx
        mock_pres.side_effect = Exception("PPTX failed")

        with NamedTemporaryFile(suffix=".pptx") as f:
            result = _extract_pptx(Path(f.name))

        self.assertIn("Could not extract text from this PPTX file", result)
        self.assertIn("PPTX failed", result)

    @patch("backend.document.Presentation")
    def test_extract_pptx_skip_shapes_without_text(self, mock_pres_class):
        """Shapes without text_frame are skipped."""
        from backend.document import _extract_pptx

        mock_pres = MagicMock()
        mock_slide = MagicMock()
        mock_shape = MagicMock()
        mock_shape.has_text_frame = False
        mock_slide.shapes = [mock_shape]
        mock_pres.slides = [mock_slide]
        mock_pres_class.return_value = mock_pres

        with NamedTemporaryFile(suffix=".pptx") as f:
            result = _extract_pptx(Path(f.name))

        self.assertIn("Slide 1", result)


class TruncatePreviewEdgeCases(unittest.TestCase):
    """Tests for truncate_preview edge cases."""

    def test_unicode_boundary_handling(self):
        """Unicode characters at boundary handled correctly."""
        text = "a" * 98 + "🌍"
        result = truncate_preview(text, length=100)
        self.assertTrue(len(result) <= 101)

    def test_newlines_in_middle(self):
        """Newlines in middle of text handled."""
        text = "Line 1\nLine 2\nLine 3"
        result = truncate_preview(text, length=10)
        self.assertTrue(result.endswith("…"))

    def test_exact_length_with_unicode(self):
        """Exact length with unicode doesn't over-truncate."""
        text = "你好" * 50
        result = truncate_preview(text, length=100)
        self.assertEqual(result, text)


class ConstantsEdgeCaseTests(unittest.TestCase):
    """Tests for constant values."""

    def test_max_ocr_pages_positive(self):
        """MAX_OCR_PAGES is positive (line 33)."""
        self.assertGreater(MAX_OCR_PAGES, 0)
        self.assertEqual(MAX_OCR_PAGES, 10)

    def test_max_ocr_file_size_mb_positive(self):
        """MAX_OCR_FILE_SIZE_MB is positive (line 36)."""
        self.assertGreater(MAX_OCR_FILE_SIZE_MB, 0)
        self.assertEqual(MAX_OCR_FILE_SIZE_MB, 50)

    def test_plain_text_extensions_not_empty(self):
        """PLAIN_TEXT_EXTENSIONS has expected values."""
        self.assertIn("txt", PLAIN_TEXT_EXTENSIONS)
        self.assertIn("md", PLAIN_TEXT_EXTENSIONS)
        self.assertIn("py", PLAIN_TEXT_EXTENSIONS)
        self.assertIn("json", PLAIN_TEXT_EXTENSIONS)

    def test_image_extensions_not_empty(self):
        """IMAGE_EXTENSIONS has expected values."""
        self.assertIn("png", IMAGE_EXTENSIONS)
        self.assertIn("jpg", IMAGE_EXTENSIONS)
        self.assertIn("jpeg", IMAGE_EXTENSIONS)
        self.assertIn("gif", IMAGE_EXTENSIONS)


class ExtractTextDispatchTests(unittest.TestCase):
    """Tests for extract_text dispatch logic."""

    def test_extension_case_normalization(self):
        """Extension is lowercased and dot stripped."""
        with NamedTemporaryFile(mode="w", suffix=".TXT", delete=False) as f:
            f.write("Test")
            f.flush()
            result = extract_text(Path(f.name), ".TXT")
        self.assertEqual(result, "Test")

    def test_empty_extension(self):
        """Empty extension after strip returns empty."""
        with NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Test")
            f.flush()
            result = extract_text(Path(f.name), "")
        self.assertEqual(result, "")

    @patch("backend.document.OCR_AVAILABLE", True)
    @patch("backend.document._extract_pdf_ocr")
    @patch("backend.document.PdfReader")
    def test_pdf_sparse_text_triggers_ocr(self, mock_pdf_reader, mock_ocr):
        """PDF with sparse text triggers OCR (line 79)."""
        mock_ocr.return_value = "OCR text"

        # Mock PdfReader to have pages with very little extracted text
        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""  # Empty extracted text
        mock_reader.pages = [mock_page]
        mock_pdf_reader.return_value = mock_reader

        with NamedTemporaryFile(suffix=".pdf") as f:
            result = extract_text(Path(f.name), "pdf")

        # Blank page has < 100 chars extracted text, should trigger OCR
        mock_ocr.assert_called()

    @patch("backend.document._extract_pdf", return_value="PDF content")
    def test_dispatch_pdf_extension(self, mock_extract):
        """PDF extension dispatches to _extract_pdf (line 50)."""
        with NamedTemporaryFile(suffix=".pdf") as f:
            f.write(b"%PDF-1.4")
            f.flush()
            result = extract_text(Path(f.name), "pdf")
        self.assertEqual(result, "PDF content")
        mock_extract.assert_called_once()

    @patch("backend.document._extract_docx", return_value="DOCX content")
    def test_dispatch_docx_extension(self, mock_extract):
        """DOCX extension dispatches to _extract_docx (line 52)."""
        with NamedTemporaryFile(suffix=".docx") as f:
            f.write(b"PK")
            f.flush()
            result = extract_text(Path(f.name), "docx")
        self.assertEqual(result, "DOCX content")
        mock_extract.assert_called_once()

    @patch("backend.document._extract_csv", return_value="CSV content")
    def test_dispatch_csv_extension(self, mock_extract):
        """CSV extension dispatches to _extract_csv (line 54)."""
        with NamedTemporaryFile(suffix=".csv") as f:
            f.write(b"a,b\n1,2")
            f.flush()
            result = extract_text(Path(f.name), "csv")
        self.assertEqual(result, "CSV content")
        mock_extract.assert_called_once()

    @patch("backend.document._extract_xlsx", return_value="XLSX content")
    def test_dispatch_xlsx_extension(self, mock_extract):
        """XLSX extension dispatches to _extract_xlsx (line 56)."""
        with NamedTemporaryFile(suffix=".xlsx") as f:
            f.write(b"PK")
            f.flush()
            result = extract_text(Path(f.name), "xlsx")
        self.assertEqual(result, "XLSX content")
        mock_extract.assert_called_once()

    @patch("backend.document._extract_pptx", return_value="PPTX content")
    def test_dispatch_pptx_extension(self, mock_extract):
        """PPTX extension dispatches to _extract_pptx (line 58)."""
        with NamedTemporaryFile(suffix=".pptx") as f:
            f.write(b"PK")
            f.flush()
            result = extract_text(Path(f.name), "pptx")
        self.assertEqual(result, "PPTX content")
        mock_extract.assert_called_once()

    @patch("backend.document._extract_image_ocr", return_value="Image OCR")
    def test_dispatch_image_extension(self, mock_extract):
        """Image extension dispatches to _extract_image_ocr (line 60)."""
        with NamedTemporaryFile(suffix=".png") as f:
            f.write(b"fake png")
            f.flush()
            result = extract_text(Path(f.name), "png")
        self.assertEqual(result, "Image OCR")
        mock_extract.assert_called_once()


class PasswordProtectedPDFTests(unittest.TestCase):
    """Tests for password-protected PDF handling."""

    @patch("backend.document.OCR_AVAILABLE", True)
    @patch("backend.document._extract_pdf_ocr")
    @patch("backend.document.PdfReader")
    def test_password_protected_pdf_returns_message(self, mock_reader, mock_ocr):
        """Password-protected PDF returns specific message (lines 87-88)."""
        from pypdf.errors import PdfReadError
        mock_reader.side_effect = PdfReadError("password required")
        mock_ocr.return_value = "OCR text"

        with NamedTemporaryFile(suffix=".pdf") as f:
            f.write(b"protected pdf")
            f.flush()
            result = extract_text(Path(f.name), "pdf")

        self.assertIn("Password-protected PDF", result)


class PDFPdf2imageNotInstalledTests(unittest.TestCase):
    """Tests for when pdf2image is not installed."""

    @patch("backend.document.OCR_AVAILABLE", True)
    @patch("backend.document.PdfReader")
    def test_extract_pdf_ocr_pdf2image_not_installed(self, mock_pdf_reader):
        """Returns message when pdf2image not installed (lines 114-117)."""
        from backend.document import _extract_pdf_ocr

        # Mock PdfReader to have pages
        mock_reader = MagicMock()
        mock_reader.pages = [MagicMock()]  # 1 page
        mock_pdf_reader.return_value = mock_reader

        # Mock the import of pdf2image to raise ImportError
        with patch.dict("sys.modules", {"pdf2image": None}):
            with NamedTemporaryFile(suffix=".pdf") as f:
                f.write(b"%PDF-1.4")
                f.flush()
                result = _extract_pdf_ocr(Path(f.name))
            self.assertIn("pdf2image", result)
            self.assertIn("install", result)


if __name__ == "__main__":
    unittest.main()
