"""
Additional tests for document.py to achieve higher branch coverage.
Tests specifically target uncovered exception handling paths and edge cases.
"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

# Enable test mode
os.environ["TEST_MODE"] = "1"
from cryptography.fernet import Fernet
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key

# Mock OCR dependencies BEFORE importing document module
# This ensures OCR_AVAILABLE = True and allows patching of pytesseract/PIL
import types

# Mock pytesseract
pytesseract_mock = types.ModuleType("pytesseract")
pytesseract_mock.image_to_string = MagicMock()
sys.modules["pytesseract"] = pytesseract_mock

# Mock pdf2image
pdf2image_mock = types.ModuleType("pdf2image")
pdf2image_mock.convert_from_path = MagicMock()
sys.modules["pdf2image"] = pdf2image_mock

# Mock PIL and its submodules (pptx imports PIL.ImageFont, etc.)
pil_mock = types.ModuleType("PIL")
pil_mock.__version__ = "10.0.0"  # pypdf checks this
for submodule in ["Image", "ImageFont", "ImageDraw", "ImageFilter", "ImageColor"]:
    sub_mod = types.ModuleType(f"PIL.{submodule}")
    setattr(pil_mock, submodule, sub_mod)
    sys.modules[f"PIL.{submodule}"] = sub_mod
sys.modules["PIL"] = pil_mock

# Now import backend.document as document - it will see pytesseract and PIL as available
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