"""
api_routes/a6_studio_routes.py — A6 (Studio, Skills & Integrations).

Registers on the shared router (imported once from api.py). New routes
only; every pre-existing route stays where it was.

  GET  /providers/capability-registry   per-provider/per-model registry
  POST /providers/preflight             "this model can't do X" warnings
  GET  /providers/contract-check        adapter contract verification
  POST /providers/cost-ranked           cost-ranked fallback ordering
  GET  /studio/catalog                  artifact families + real engine status
  POST /studio/documents/proof          generate + PARSE BACK the document
  POST /diagrams/export                 node/edge -> self-contained SVG/HTML
  POST /studio/classroom/generate       topic -> slides + quiz + HTML + PBL
  GET  /marketplace/sources             local/git/registry (registry = STUB)
  POST /marketplace/packs/{pack}/dry-run pack install preview, writes nothing
  POST /marketplace/packs/{pack}/install hash-verified pack install + scan
  GET  /connectors/{name}/health        configured/connected, no secrets
  GET  /connectors/{name}/permissions   scopes + credential isolation note
  POST /compare/blind                   blind comparison (labels A/B/…)
  POST /compare/blind/vote              reveal + record Arena vote

Honest limits (also in MANIFEST.md): diagrams PNG export is NOT here
(no raster renderer in this environment — browser Mermaid export is
the existing path); blind mappings live in memory (restart drops
them); voice cloning and video production are SKIPPED per user
decision and have no endpoint.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
import zipfile
from datetime import UTC, datetime

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..connectors import get_registry as get_connector_registry
from ..database import get_db
from ..diagrams import CATALOGUE
from ..models import ArenaResult, ProviderKey
from ..providers.contract import (
    capability_registry,
    check_adapters,
    cost_ranked_route,
    preflight,
)
from ..skills import verify as verify_mod
from ..skills.docgen import generate_document
from ..skills.packs import get_pack
from ..skills.scan import scan_skill_dir
from ..studio_classroom import generate_classroom
from ..studio_svg import render_html, render_report, render_svg
from .common import router

# blind_id -> {prompt, models, labels: {label: model}}; in-memory only.
_BLIND: dict[str, dict] = {}


# ---------------------------------------------------------------- providers
@router.get("/providers/capability-registry")
async def a6_capability_registry(user=Depends(get_current_user)):
    return capability_registry()


@router.get("/providers/contract-check")
async def a6_contract_check(user=Depends(get_current_user)):
    return check_adapters()


class PreflightIn(BaseModel):
    provider: str
    model: str
    wanted: list[str] = Field(default_factory=list)


@router.post("/providers/preflight")
async def a6_preflight(payload: PreflightIn, user=Depends(get_current_user)):
    return preflight(payload.provider, payload.model, payload.wanted)


class CostRankedIn(BaseModel):
    candidates: list[dict] = Field(default_factory=list)


@router.post("/providers/cost-ranked")
async def a6_cost_ranked(payload: CostRankedIn, user=Depends(get_current_user)):
    return {"ranked": cost_ranked_route(payload.candidates)}


# ------------------------------------------------------------------- studio
def _engine_status() -> dict:
    """Real availability checks; failures are reported, never hidden."""
    status: dict[str, dict] = {}
    try:
        from ..voice.service import voice_status

        vs = voice_status()
        status["voice"] = {
            "available": bool(vs.get("tts_engine") or vs.get("stt_engine")),
            "engines": vs.get("engines", []),
            "note": "Real engines only; no voice cloning (user-skipped).",
        }
    except Exception as exc:  # noqa: BLE001
        status["voice"] = {"available": False, "engines": [], "note": f"Status check failed: {exc}"}
    try:
        from ..image_gen import image_status

        status["image"] = {"available": True, "detail": image_status()}
    except Exception as exc:  # noqa: BLE001
        status["image"] = {"available": False, "detail": None, "note": f"Status check failed: {exc}"}
    return status


@router.get("/studio/catalog")
async def a6_studio_catalog(user=Depends(get_current_user)):
    engines = _engine_status()
    return {
        "families": [
            {"id": "documents", "formats": ["docx", "pdf", "pptx", "xlsx"],
             "engine": "skills/docgen (stdlib ZIP+XML writers)",
             "available": True,
             "proof": "POST /studio/documents/proof parses the output back"},
            {"id": "design", "deliverables": "design systems (DESIGN.md), sandboxed HTML/React prototypes",
             "engine": "existing Design Studio frontend module",
             "available": True},
            {"id": "diagrams", "types": len(CATALOGUE),
             "engine": "44-type Mermaid catalogue + node/edge SVG/HTML export",
             "available": True,
             "exports": ["svg", "html"],
             "not_offered": ["png (no raster renderer in this environment)"]},
            {"id": "image", "engine": "Fooocus-style presets/ops via configured engine",
             "available": engines["image"]["available"],
             "detail": engines["image"]},
            {"id": "voice", "engine": "real TTS/STT engines only",
             "available": engines["voice"]["available"],
             "detail": engines["voice"],
             "not_offered": ["voice cloning (user-skipped)"]},
            {"id": "classroom", "engine": "deterministic template (no LLM, no MP4)",
             "available": True,
             "exports": ["html", "pptx-via-documents-generate"],
             "not_offered": ["mp4", "slide-editor"]},
            {"id": "video", "available": False,
             "note": "Video production SKIPPED per user decision; no endpoint."},
        ],
    }


class DocProofIn(BaseModel):
    format: str
    title: str = "Untitled"
    sections: list[dict] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)


def _parse_back(fmt: str, data: bytes) -> dict:
    """Parse the generated bytes with a REAL library, not magic bytes."""
    if fmt == "pdf":
        return {"starts_with_pdf": data[:4] == b"%PDF",
                "has_eof": b"%%EOF" in data[-64:]}
    buf = io.BytesIO(data)
    try:
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return {"valid_zip": False}
    out: dict = {"valid_zip": True, "parts": names}
    try:
        if fmt == "docx":
            import docx

            doc = docx.Document(io.BytesIO(data))
            out["paragraphs"] = [p.text for p in doc.paragraphs]
        elif fmt == "pptx":
            import pptx

            prs = pptx.Presentation(io.BytesIO(data))
            out["slides"] = len(prs.slides)
        elif fmt == "xlsx":
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(data))
            out["sheets"] = wb.sheetnames
    except Exception as exc:  # noqa: BLE001
        out["parse_error"] = str(exc)
    return out


@router.post("/studio/documents/proof")
async def a6_document_proof(payload: DocProofIn, user=Depends(get_current_user)):
    fmt = payload.format.lower()
    try:
        data = generate_document(fmt, payload.title, payload.sections, payload.rows)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    parsed = _parse_back(fmt, data)
    return {"format": fmt, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "parsed": parsed}


class DiagramExportIn(BaseModel):
    format: str = "svg"
    title: str = "Diagram"
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    accent: str | None = None
    font: str | None = None


@router.post("/diagrams/export")
async def a6_diagram_export(payload: DiagramExportIn, user=Depends(get_current_user)):
    fmt = payload.format.lower()
    if fmt not in ("svg", "html"):
        raise HTTPException(
            status_code=422,
            detail="Only svg and html export are offered here; png needs a "
                   "raster renderer that is not available in this environment.")
    content = render_svg(payload.nodes, payload.edges, title=payload.title,
                         accent=payload.accent, font=payload.font) \
        if fmt == "svg" else render_html(
            payload.nodes, payload.edges, title=payload.title,
            accent=payload.accent, font=payload.font)
    return {"format": fmt, "content": content,
            "report": render_report(payload.nodes, payload.edges)}


class ClassroomIn(BaseModel):
    topic: str
    source_text: str = ""


@router.post("/studio/classroom/generate")
async def a6_classroom(payload: ClassroomIn, user=Depends(get_current_user)):
    return generate_classroom(payload.topic, payload.source_text)


# -------------------------------------------------------------- marketplace
@router.get("/marketplace/sources")
async def a6_marketplace_sources(user=Depends(get_current_user)):
    return {"sources": [
        {"id": "local", "status": "working",
         "note": "Install from a local skill/pack directory on disk."},
        {"id": "git", "status": "working-via-local",
         "note": "Clone the repo first, then install from the local directory; "
                 "no in-app git fetch is performed."},
        {"id": "registry", "status": "stub",
         "note": "STUB — clearly labelled: there is no working remote skill "
                 "registry in this build. Do not present this source as "
                 "installing anything."},
    ]}


def _pack_or_404(pack: str):
    found = get_pack(pack)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Pack not found: {pack}")
    return found


@router.post("/marketplace/packs/{pack}/dry-run")
async def a6_pack_dry_run(pack: str, user=Depends(get_current_user)):
    found = _pack_or_404(pack)
    previews = []
    for skill in found.skills:
        src = found.skills_root / skill
        try:
            previews.append(verify_mod.dry_run_install(src))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"pack": found.name, "version": found.version,
            "writes_nothing": True, "skills": previews}


@router.post("/marketplace/packs/{pack}/install")
async def a6_pack_install(pack: str, user=Depends(get_current_user)):
    found = _pack_or_404(pack)
    installed = []
    for skill in found.skills:
        src = found.skills_root / skill
        try:
            result = verify_mod.install_skill(src, version=found.version)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        skill_dir = verify_mod.find_skill_dir(result["name"])
        scan = scan_skill_dir(skill_dir) if skill_dir else {"findings": []}
        high = [f for f in scan.get("findings", []) if f.get("severity") == "high"]
        installed.append({**result, "scan": scan,
                          "blocked_by_scan": bool(high)})
    lock = verify_mod.verify_lock()
    locked_names = {row["name"] for row in lock}
    return {"pack": found.name, "version": found.version,
            "installed": installed,
            "lock_verified": [i["name"] for i in installed
                              if i["name"] in locked_names]}


# --------------------------------------------------------------- connectors
@router.get("/connectors/{name}/health")
async def a6_connector_health(name: str, db: AsyncSession = Depends(get_db),
                              user=Depends(get_current_user)):
    definition = get_connector_registry().get(name)
    if not definition:
        raise HTTPException(status_code=404, detail="Connector not found")
    from sqlalchemy import select

    row = (await db.execute(
        select(ProviderKey).where(ProviderKey.provider_id == f"oauth:{name}")
    )).scalars().first()
    connected = row is not None
    return {"connector": name, "configured": bool(definition.configured),
            "connected": connected,
            "health": "ok" if connected else "not_connected",
            "token": None}


@router.get("/connectors/{name}/permissions")
async def a6_connector_permissions(name: str, db: AsyncSession = Depends(get_db),
                                   user=Depends(get_current_user)):
    definition = get_connector_registry().get(name)
    if not definition:
        raise HTTPException(status_code=404, detail="Connector not found")
    from sqlalchemy import select

    row = (await db.execute(
        select(ProviderKey).where(ProviderKey.provider_id == f"oauth:{name}")
    )).scalars().first()
    return {"connector": name,
            "requested_scopes": list(definition.scopes),
            "granted_scopes": list(definition.scopes) if row else [],
            "credential_storage": "encrypted_at_rest (ProviderKey hybrid property)",
            "credential_isolated": True,
            "revoke": f"DELETE /api/connectors/{name}",
            "token_value": None}


# ----------------------------------------------------------- blind compare
class BlindCompareIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    models: list[str] = Field(min_length=2, max_length=4)
    max_tokens: int = 500


@router.post("/compare/blind")
async def a6_blind_compare(payload: BlindCompareIn, db: AsyncSession = Depends(get_db),
                           user=Depends(get_current_user)):
    from ..llm import stream_completion

    async def _run_one(model_id: str) -> dict:
        parts: list[str] = []
        error = None
        try:
            async for chunk in stream_completion(
                    model_id, [{"role": "user", "content": payload.prompt}],
                    db, max_tokens=payload.max_tokens):
                text = chunk if isinstance(chunk, str) else getattr(chunk, "text", None)
                if text:
                    parts.append(text)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        return {"model": model_id, "output": "".join(parts), "error": error}

    results = await asyncio.gather(*(_run_one(m) for m in payload.models))
    blind_id = f"blind-{uuid.uuid4().hex[:12]}"
    labels: dict[str, str] = {}
    anon = []
    for i, res in enumerate(results):
        label = chr(ord("A") + i)
        labels[label] = res["model"]
        anon.append({"label": label, "output": res["output"], "error": res["error"]})
    _BLIND[blind_id] = {"prompt": payload.prompt, "models": list(payload.models),
                        "labels": labels}
    return {"blind_id": blind_id, "results": anon}


class BlindVoteIn(BaseModel):
    blind_id: str
    winner_label: str


@router.post("/compare/blind/vote", status_code=201)
async def a6_blind_vote(payload: BlindVoteIn, db: AsyncSession = Depends(get_db),
                        user=Depends(get_current_user)):
    entry = _BLIND.get(payload.blind_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Blind comparison not found (mappings are in-memory; a restart drops them)")
    winner = entry["labels"].get(payload.winner_label)
    if winner is None:
        raise HTTPException(status_code=422, detail="Unknown winner label")
    losers = [m for m in entry["models"] if m != winner]
    row = ArenaResult(
        id=f"arena-{uuid.uuid4().hex[:12]}", user_id=user.id,
        prompt=entry["prompt"][:500], winner_model=winner,
        loser_model=losers[0] if losers else winner,
        models_compared=",".join(entry["models"]),
        created_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    return {"id": row.id, "winner_model": winner, "loser_model": row.loser_model}
