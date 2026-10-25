"""Filesystem artifact store for spec pipelines.

The database stage rows are the system of record (they survive a
restart); this store mirrors each stage artifact to a markdown file
so a pipeline can be inspected, diffed, and archived outside the DB:

  <root>/<pipeline_id>/constitution.md
  <root>/<pipeline_id>/spec.md
  <root>/<pipeline_id>/plan.md
  <root>/<pipeline_id>/checklist.md
  <root>/<pipeline_id>/tasks.md
  <root>/<pipeline_id>/analyze.md
  <root>/<pipeline_id>/implement.md
  <root>/<pipeline_id>/verify.md
  <root>/<pipeline_id>/converge-report.md
  <root>/<pipeline_id>/review-pr.md   (auxiliary, not a stage)

Paths are confined under ``root``: a pipeline id containing a path
separator is rejected rather than escaped. Writes are atomic
(temp file + rename) so a crashed write never leaves a half file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_STAGE_FILES = {
    "constitution": "constitution.md",
    "spec": "spec.md",
    "clarify": "clarify.md",
    "plan": "plan.md",
    "checklist": "checklist.md",
    "tasks": "tasks.md",
    "analyze": "analyze.md",
    "implement": "implement.md",
    "verify": "verify.md",
    "converge": "converge-report.md",
    "review-pr": "review-pr.md",
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ArtifactStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _dir(self, pipeline_id: str) -> Path:
        if not _SAFE_ID.match(pipeline_id or ""):
            raise ValueError(f"unsafe pipeline id: {pipeline_id!r}")
        return self.root / pipeline_id

    def write(self, pipeline_id: str, stage: str, artifact: str) -> Path:
        filename = _STAGE_FILES.get(stage)
        if filename is None:
            raise ValueError(f"no artifact file for stage {stage!r}")
        d = self._dir(pipeline_id)
        d.mkdir(parents=True, exist_ok=True)
        target = d / filename
        tmp = d / (filename + ".tmp")
        tmp.write_text(artifact or "", encoding="utf-8")
        tmp.replace(target)
        index = d / "index.json"
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data[stage] = filename
        index.write_text(json.dumps(data, indent=2, sort_keys=True),
                         encoding="utf-8")
        return target

    def read(self, pipeline_id: str, stage: str) -> str | None:
        filename = _STAGE_FILES.get(stage)
        if filename is None:
            return None
        path = self._dir(pipeline_id) / filename
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def list_artifacts(self, pipeline_id: str) -> list[str]:
        d = self._dir(pipeline_id)
        if not d.is_dir():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_file()
                      and p.name != "index.json" and not p.name.endswith(".tmp"))
