"""
api_routes/files_routes.py — document upload endpoint (validation, storage,
text extraction, RAG indexing).
"""
import re
import uuid
from pathlib import Path

from fastapi import Depends, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..document import extract_text, truncate_preview
from ..models import UploadedFile
from ..rag import index_document
from ..schemas import FileUploadOut
from .common import _get_magic, router

# Magic byte validator for file uploads
# Maps extension to expected MIME types (using python-magic)
ALLOWED_MIME_TYPES = {
    "pdf": ["application/pdf"],
    "docx": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    "txt": ["text/plain"],
    "csv": ["text/csv"],
    "xlsx": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
    "pptx": ["application/vnd.openxmlformats-officedocument.presentationml.presentation"],
    "json": ["application/json"],
    "html": ["text/html"],
    "xml": ["application/xml", "text/xml"],
    "md": ["text/markdown"],
    "py": ["text/x-python", "text/plain"],
    "java": ["text/x-java", "text/plain"],
    "js": ["text/javascript", "application/javascript", "text/plain"],
    "c": ["text/x-c", "text/plain"],
    "cpp": ["text/x-c++src", "text/plain"],
    "cs": ["text/x-csharp", "text/plain"],
    "go": ["text/x-go", "text/plain"],
    "rs": ["text/x-rust", "text/plain"],
    "php": ["application/x-php", "text/plain"],
    "sql": ["application/sql", "text/plain"],
    "r": ["text/plain"],
}

@router.post("/files", response_model=FileUploadOut)
async def upload_file(request: Request, file: UploadFile, db: AsyncSession = Depends(get_db)):
    """Upload a document, extract its text and index it for RAG."""
    filename = Path(file.filename or "upload").name
    if not filename or filename == ".":
        raise HTTPException(status_code=400, detail="A valid filename is required")
    # Prevent path traversal via ..\ or ../ sequences in the filename
    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)

    extension = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if extension not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: .{extension}")

    # Early size check via Content-Length — reject before reading into memory
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            size_mb = int(content_length) / (1024 * 1024)
            if size_mb > settings.MAX_UPLOAD_SIZE_MB:
                raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit")
        except ValueError:
            pass  # Malformed header — fall through to the read-based check below

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > settings.MAX_UPLOAD_SIZE_MB:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit")

    # Magic byte validation — skipped gracefully when libmagic is unavailable.
    _magic = _get_magic()
    if _magic:
        try:
            detected_mime = _magic.from_buffer(contents)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Could not determine file type") from exc

        allowed_mimes = ALLOWED_MIME_TYPES.get(extension, [])
        if allowed_mimes and detected_mime not in allowed_mimes:
            raise HTTPException(
                status_code=415,
                detail=f"File content does not match extension .{extension}. Detected: {detected_mime}",
            )

    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex[:12]}_{filename}"
    stored_path = settings.UPLOAD_DIR / stored_name
    stored_path.write_bytes(contents)

    extracted = extract_text(stored_path, extension)

    record = UploadedFile(
        filename=filename,
        stored_path=str(stored_path),
        extension=extension,
        size_bytes=len(contents),
        extracted_text=extracted,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    # Index for RAG — non-blocking, a failure never breaks the upload
    if extracted:
        index_document(record.id, extracted, filename)

    return FileUploadOut(
        file_id=record.id,
        filename=record.filename,
        extension=record.extension,
        size_bytes=record.size_bytes,
        preview=truncate_preview(extracted) if extracted else None,
    )


