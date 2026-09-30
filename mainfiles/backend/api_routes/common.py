"""
api_routes/common.py — SSE framing and upload-content validation helpers
shared by the route modules.
"""
import asyncio
import logging

from fastapi import (
    APIRouter,  # All route modules register onto this shared router pair. The package
)

from ..response_events import ResponseEvent

# ``__init__`` exposes them; api.py (the facade) mounts them.
router = APIRouter()
public_router = APIRouter()

logger = logging.getLogger(__name__)

# Phase 5: strong references to fire-and-forget tasks so the event loop
# doesn't garbage-collect them mid-flight.
_background_tasks: set[asyncio.Task] = set()


def sse_event(data: str, event: str | None = None) -> str:
    """Format data as a Server-Sent Event (SSE) string.

    Args:
        data: The data to send in the event
        event: Optional event type

    Returns:
        Formatted SSE string
    """
    if event:
        lines = [f"event: {event}"]
    else:
        lines = []


    # Handle multiline data by splitting into multiple data: lines
    # But preserve SSE comment lines (starting with :) as-is
    if "\n" in data or "\r" in data:
        # Normalize line endings and split
        lines_data = data.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        for line in lines_data:
            if line.startswith(":"):
                # SSE comment line - preserve as-is
                lines.append(line)
            else:
                lines.append(f"data: {line}")
    elif data.startswith(":"):
        # SSE comment line - preserve as-is
        lines.append(data)
    else:
        lines.append(f"data: {data}")

    lines.append("")  # Empty line to end the event
    return "\n".join(lines) + "\n"


def sse_response_event(event: ResponseEvent) -> str:
    """Serialize a canonical response event as an SSE frame."""
    return sse_event(event.to_json(), event="response_event")


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

# Optional dependency: python-magic requires the system libmagic shared
# library (apt: libmagic1, brew: libmagic) in addition to the pip package.
# If either is missing, degrade gracefully to extension-only validation
# (already enforced above) instead of crashing the whole app at import time —
# same pattern used for OCR in document.py.
_magic = None
MAGIC_AVAILABLE = False

def _get_magic():
    """Lazy initialization of python-magic to avoid import-time crashes on Windows."""
    global _magic, MAGIC_AVAILABLE
    if _magic is not None or MAGIC_AVAILABLE is False:
        return _magic
    try:
        import magic
        _magic = magic.Magic(mime=True)
        MAGIC_AVAILABLE = True
    except Exception:  # noqa: BLE001 — missing package or missing system libmagic
        _magic = None
        MAGIC_AVAILABLE = False
        from loguru import logger
        logger.warning(
            "python-magic / libmagic not available — file uploads will only be "
            "validated by extension."
        )
    return _magic
