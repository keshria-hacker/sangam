"""
Project-wide pytest bootstrap.

Puts the project root and `<root>/mainfiles` on `sys.path` so every test tree
can use the canonical import style:

    from backend.api import router      # <root>/mainfiles/backend/...

Loaded by pytest before any test module is imported, so the path setup applies
to `tests/` and `mainfiles/backend/tests/` alike.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

for _path in (str(ROOT), str(ROOT / "mainfiles")):
    if _path not in sys.path:
        sys.path.insert(0, _path)
