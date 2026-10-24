"""
api_routes/system_routes.py — Phase 5: system backup download.

GET /system/backup streams a zip of the SQLite database (consistent
copy via sqlite3's backup API) plus the uploads tree. Restore is
deliberately NOT an API endpoint: replacing a live database while
the server holds it open is unsafe, so restore is a CLI operation
(``python -m cli restore``) run while the server is stopped.
"""
import io
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from fastapi import Depends
from fastapi.responses import StreamingResponse

from ..auth import get_current_user
from ..config import settings
from .common import router


def _db_path() -> Path | None:
    url = settings.DATABASE_URL or ""
    if url.startswith("sqlite+aiosqlite:///"):
        return Path(url[len("sqlite+aiosqlite:///"):])
    if url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///"):])
    return None


@router.get("/system/backup")
async def download_backup(user=Depends(get_current_user)):
    db_path = _db_path()
    if db_path is None or not db_path.exists():
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="Backup requires a file-based SQLite database")
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "sangam.db"
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(str(tmp_db))
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_db, arcname="sangam.db")
            uploads = Path(settings.UPLOAD_DIR)
            if uploads.exists():
                for path in sorted(uploads.rglob("*")):
                    if path.is_file():
                        zf.write(path, arcname=str(Path("uploads") / path.relative_to(uploads)))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=sangam-backup.zip"},
    )
