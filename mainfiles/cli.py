"""
cli.py — Phase 5: Sangam command-line interface (stdlib only).

Usage:
  python -m cli health
  python -m cli workflows list
  python -m cli workflows run <id> --input '{"name": "Ada"}'
  python -m cli knowledge retrieve "sunlight photosynthesis"
  python -m cli media jobs
  python -m cli media create tts --text "Hello"
  python -m cli runs list
  python -m cli backup <output.zip>
  python -m cli restore <backup.zip> --data-dir <dir> [--confirm]

Auth: SANGAM_TOKEN env (Bearer). Server: SANGAM_URL env
(default http://127.0.0.1:8001). Backup/restore are offline file
operations: backup zips the SQLite database (consistent copy via
sqlite3's backup API) plus the uploads tree; restore replaces them
into a data directory while the server is stopped — it refuses to
run against a live database directory without --confirm, and it
never touches a running server's open handles itself.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sangam_client import SangamClient, SangamError  # noqa: E402


def _client(args) -> SangamClient:
    return SangamClient(base_url=args.url, token=args.token)


def _print_json(data) -> None:
    print(json.dumps(data, indent=2, default=str))


def cmd_health(args) -> int:
    _print_json(_client(args).health())
    return 0


def cmd_workflows_list(args) -> int:
    _print_json(_client(args).list_workflows())
    return 0


def cmd_workflows_run(args) -> int:
    data = json.loads(args.input) if args.input else {}
    _print_json(_client(args).run_workflow(args.workflow_id, data, args.idempotency_key))
    return 0


def cmd_knowledge_retrieve(args) -> int:
    _print_json(_client(args).retrieve(args.query, args.top_k))
    return 0


def cmd_media_jobs(args) -> int:
    _print_json(_client(args).list_media_jobs())
    return 0


def cmd_media_create(args) -> int:
    kwargs: dict = {}
    if args.text:
        kwargs["text"] = args.text
    if args.prompt:
        kwargs["prompt"] = args.prompt
    if args.media_id:
        kwargs["media_id"] = args.media_id
    _print_json(_client(args).create_media_job(args.kind, **kwargs))
    return 0


def cmd_runs_list(args) -> int:
    _print_json(_client(args).list_runs())
    return 0


def backup_zip(db_path: Path, uploads_dir: Path, output: Path) -> Path:
    """Consistent SQLite copy + uploads tree into a zip."""
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")
    tmp_db = output.with_suffix(".tmp.db")
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(str(tmp_db))
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    try:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_db, arcname="sangam.db")
            if uploads_dir.exists():
                for path in sorted(uploads_dir.rglob("*")):
                    if path.is_file():
                        zf.write(path, arcname=str(Path("uploads") / path.relative_to(uploads_dir)))
    finally:
        tmp_db.unlink(missing_ok=True)
    return output


def restore_zip(backup: Path, data_dir: Path) -> None:
    """Replace a data directory's database + uploads from a backup zip.

    The zip must contain sangam.db. Existing files are moved aside
    to *.bak before replacement, so a failed restore is recoverable.
    """
    if not backup.exists():
        raise SystemExit(f"Backup not found: {backup}")
    with zipfile.ZipFile(backup) as zf:
        names = zf.namelist()
        if "sangam.db" not in names:
            raise SystemExit("Backup is invalid: no sangam.db inside")
        data_dir.mkdir(parents=True, exist_ok=True)
        db_target = data_dir / "sangam.db"
        if db_target.exists():
            shutil.move(str(db_target), str(db_target) + ".bak")
        uploads_target = data_dir / "uploads"
        if uploads_target.exists():
            shutil.move(str(uploads_target), str(uploads_target) + ".bak")
        zf.extractall(data_dir)


def cmd_backup(args) -> int:
    out = backup_zip(Path(args.db), Path(args.uploads), Path(args.output))
    print(f"Backup written: {out}")
    return 0


def cmd_restore(args) -> int:
    if not args.confirm:
        print("Refusing: pass --confirm to restore (stop the server first).")
        return 2
    restore_zip(Path(args.backup), Path(args.data_dir))
    print(f"Restored into {args.data_dir} (previous files kept as *.bak). Restart the server.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sangam")
    p.add_argument("--url", default=os.environ.get("SANGAM_URL", "http://127.0.0.1:8001"))
    p.add_argument("--token", default=os.environ.get("SANGAM_TOKEN", ""))
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("health").set_defaults(func=cmd_health)

    wf = sub.add_parser("workflows").add_subparsers(dest="wf_cmd", required=True)
    wf.add_parser("list").set_defaults(func=cmd_workflows_list)
    run = wf.add_parser("run")
    run.add_argument("workflow_id")
    run.add_argument("--input", default="{}")
    run.add_argument("--idempotency-key", default=None)
    run.set_defaults(func=cmd_workflows_run)

    kn = sub.add_parser("knowledge").add_subparsers(dest="kn_cmd", required=True)
    ret = kn.add_parser("retrieve")
    ret.add_argument("query")
    ret.add_argument("--top-k", type=int, default=5)
    ret.set_defaults(func=cmd_knowledge_retrieve)

    md = sub.add_parser("media").add_subparsers(dest="md_cmd", required=True)
    md.add_parser("jobs").set_defaults(func=cmd_media_jobs)
    create = md.add_parser("create")
    create.add_argument("kind")
    create.add_argument("--text", default=None)
    create.add_argument("--prompt", default=None)
    create.add_argument("--media-id", default=None)
    create.set_defaults(func=cmd_media_create)

    runs = sub.add_parser("runs").add_subparsers(dest="runs_cmd", required=True)
    runs.add_parser("list").set_defaults(func=cmd_runs_list)

    bk = sub.add_parser("backup")
    bk.add_argument("output")
    bk.add_argument("--db", default="mainfiles/sangam.db")
    bk.add_argument("--uploads", default="mainfiles/uploads")
    bk.set_defaults(func=cmd_backup)

    rs = sub.add_parser("restore")
    rs.add_argument("backup")
    rs.add_argument("--data-dir", required=True)
    rs.add_argument("--confirm", action="store_true")
    rs.set_defaults(func=cmd_restore)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SangamError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
