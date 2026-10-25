"""api_routes/media_pipeline_routes.py — Batch 11 unified media routes.

All routes reuse the shared router + contracts error envelope. No
endpoint here accepts a reference-audio voice, a speaker embedding, a
face image, or a video kind — those requests are rejected (422/404),
and the exclusion tests assert the absence, not just missing UI.

Routes:
  POST /voice/dub            true dubbing (timed segments -> SRT/VTT/ASS)
  POST /voice/tts/chunked    chunked long-form TTS (WAV join)
  POST /voice/audiobook      audiobook plan (+ manifest)
  POST /diagrams/validate    typed-IR validation (erd/sequence/workflow/
                             timeline + architecture)
  POST /diagrams/verify      layout verifier (4px grid, accent, budgets,
                             overlap on computed geometry)
  POST /diagrams/export      standalone HTML+SVG export
  POST /design-systems       design-system contract CRUD (file-backed)
  POST /design-systems/{id}/critique
  POST /design-systems/{id}/transform   bolder/quieter/distill
  POST /media/graph/validate  node-graph validation
  POST /media/graph/run       node-graph execution via existing engines
  POST /media/overlay         non-destructive SVG overlay render
  POST /media/storyboard      scene plan -> still-image prompts
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import Depends, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..diagram_ir import (
    erd_junctions,
    export_html_svg,
    validate_diagram,
    verify_layout,
)
from ..feature_flags import is_enabled
from ..media_pipeline.audio import (
    audiobook_plan,
    fit_script_to_segments,
    label_segments,
    render_ass_word_level,
    render_srt,
    render_vtt,
    validate_segments,
)
from ..media_pipeline.design import (
    critique_prototype,
    rebuild_from_css,
    transform_contract,
    validate_contract,
)
from ..media_pipeline.graph import (
    NODE_DEFS,
    execute_graph,
    validate_graph,
)
from ..media_pipeline.overlay import render_overlay_svg, validate_annotations
from ..media_pipeline.storyboard import still_prompts, validate_scene_plan
from .common import router


def _require_voice() -> None:
    if not is_enabled("voice"):
        raise HTTPException(status_code=404, detail="Voice is not enabled")


# ---------------------------------------------------------------- true dub

class DubIn(BaseModel):
    segments: list[dict] | None = None
    script: str | None = None
    turns: list[dict] | None = None
    # No reference_audio / voice_clone / speaker_embedding field exists
    # here on purpose: cloning is excluded, and any such field sent by
    # a caller is ignored by Pydantic (not stored, not used).


@router.post("/voice/dub")
async def true_dub(payload: DubIn, user=Depends(get_current_user)):
    """TRUE dubbing, distinct from the media-jobs ``dub`` kind (which
    only voices a script). Timed segments are fitted to a script and
    exported as SRT/VTT/word-level ASS. Timings come from the supplied
    segments only — this route never invents timings, and it does not
    accept source audio for ASR here: upload + transcribe first, then
    pass the timed segments (a future STT engine exposing segments
    will fill them in automatically)."""
    _require_voice()
    if not payload.segments:
        raise HTTPException(
            status_code=422,
            detail="True dubbing needs timed segments [{start, end, text}]. "
                   "Sangam's current STT engines return plain text without "
                   "timings, so segments must be supplied explicitly; "
                   "timings are never invented.")
    errs = validate_segments(payload.segments)
    if errs:
        raise HTTPException(status_code=422, detail=errs[0]["message"])
    segments = payload.segments
    if payload.turns:
        segments = label_segments(segments, payload.turns)
    fitted = fit_script_to_segments(segments, payload.script or "")
    return {"segments": fitted, "srt": render_srt(fitted),
            "vtt": render_vtt(fitted), "ass": render_ass_word_level(fitted),
            "diarization": "labels carried from supplied segments/turns only; "
                           "no speaker identity is inferred or cloned"}


class ChunkedTTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    voice: str | None = None
    max_chars: int = Field(default=800, ge=100, le=2000)
    gap_ms: int = Field(default=250, ge=0, le=2000)


@router.post("/voice/tts/chunked")
async def chunked_tts(payload: ChunkedTTSIn, user=Depends(get_current_user)):
    """Chunked long-form TTS; returns joined WAV bytes."""
    _require_voice()
    from ..voice import VoiceError, synthesize_chunked
    try:
        out = synthesize_chunked(payload.text, payload.voice,
                                 max_chars=payload.max_chars, gap_ms=payload.gap_ms)
    except VoiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=out["audio"], media_type=out["mime"],
                    headers={"X-TTS-Chunks": str(len(out["chunks"]))})


class AudiobookIn(BaseModel):
    text: str | None = None
    chapters: list[dict] | None = None
    seed: int = 0


@router.post("/voice/audiobook")
async def audiobook_endpoint(payload: AudiobookIn, user=Depends(get_current_user)):
    """Audiobook plan (chapters/spans/deterministic seeds) + chaptered
    export manifest. Rendering is the media-jobs ``audiobook`` kind;
    this endpoint is the plan step, so a plan can be reviewed before
    any voicing spend."""
    _require_voice()
    if not (payload.text or "").strip() and not payload.chapters:
        raise HTTPException(status_code=422, detail="audiobook needs text or chapters")
    return audiobook_plan(payload.text or "", seed=payload.seed,
                          chapters=payload.chapters)


# ---------------------------------------------------------------- diagrams

class DiagramValidateIn(BaseModel):
    diagram: dict


@router.post("/diagrams/validate")
async def diagrams_validate(payload: DiagramValidateIn, user=Depends(get_current_user)):
    diags = validate_diagram(payload.diagram)
    extra = {}
    if payload.diagram.get("diagram_type") == "erd":
        extra["junctions"] = erd_junctions(payload.diagram)
    return {"valid": diags == [], "diagnostics": diags, **extra}


class DiagramVerifyIn(BaseModel):
    nodes: list[dict]
    accent: str | None = None
    accents_used: list[str] | None = None


@router.post("/diagrams/verify")
async def diagrams_verify(payload: DiagramVerifyIn, user=Depends(get_current_user)):
    findings = verify_layout(payload.nodes, accent=payload.accent,
                             accents_used=payload.accents_used)
    return {"valid": findings == [], "findings": findings,
            "note": "Overlap is checked on the supplied computed geometry. "
                    "Mermaid text has no geometry, so its lint stays "
                    "text-only (see POST /diagrams/lint)."}


class DiagramExportIn(BaseModel):
    diagram: dict
    nodes: list[dict] | None = None
    accent: str | None = "#3A7BD5"


@router.post("/diagrams/export")
async def diagrams_export(payload: DiagramExportIn, user=Depends(get_current_user)):
    diags = validate_diagram(payload.diagram)
    if diags:
        raise HTTPException(status_code=422, detail=diags[0]["message"])
    return Response(content=export_html_svg(payload.diagram, payload.nodes,
                                            accent=payload.accent or "#3A7BD5"),
                    media_type="text/html")


# ---------------------------------------------------------------- design

def _design_dir() -> Path:
    d = settings.UPLOAD_DIR / "design-systems"
    d.mkdir(parents=True, exist_ok=True)
    return d


class DesignSystemIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    tokens: dict = Field(default_factory=dict)
    evidence: list[dict] = Field(default_factory=list)
    css_source: str | None = None
    css_source_name: str | None = None


@router.post("/design-systems")
async def create_design_system(payload: DesignSystemIn, user=Depends(get_current_user)):
    if payload.css_source:
        contract = rebuild_from_css(payload.css_source,
                                    payload.css_source_name or "css-source",
                                    payload.name)
        # Caller tokens override rebuilt ones group-wise.
        for group, group_tokens in payload.tokens.items():
            contract["tokens"].setdefault(group, {}).update(group_tokens or {})
        contract["evidence"] = (contract.get("evidence") or []) + payload.evidence
    else:
        contract = {"name": payload.name, "version": 1,
                    "tokens": payload.tokens, "evidence": payload.evidence}
    errs = validate_contract(contract)
    if errs:
        raise HTTPException(status_code=422, detail=errs[0]["message"])
    sid = f"{user.id}-{uuid.uuid4().hex[:12]}"
    contract["id"] = sid
    (_design_dir() / f"{sid}.json").write_text(json.dumps(contract), encoding="utf-8")
    return contract


def _load_design_system(sid: str, user) -> dict:
    path = _design_dir() / f"{sid}.json"
    if not sid.startswith(f"{user.id}-") or not path.exists():
        raise HTTPException(status_code=404, detail="Design system not found")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/design-systems")
async def list_design_systems(user=Depends(get_current_user)):
    out = []
    for path in sorted(_design_dir().glob(f"{user.id}-*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            continue
    return {"systems": out}


class CritiqueIn(BaseModel):
    html: str = Field(min_length=1)


@router.post("/design-systems/{sid}/critique")
async def critique_design_system(sid: str, payload: CritiqueIn,
                                 user=Depends(get_current_user)):
    contract = _load_design_system(sid, user)
    findings = critique_prototype(payload.html, contract)
    return {"findings": findings, "contract": contract["name"]}


class TransformIn(BaseModel):
    operation: str


@router.post("/design-systems/{sid}/transform")
async def transform_design_system(sid: str, payload: TransformIn,
                                  user=Depends(get_current_user)):
    contract = _load_design_system(sid, user)
    try:
        out = transform_contract(contract, payload.operation)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    out["contract"]["id"] = sid
    (_design_dir() / f"{sid}.json").write_text(json.dumps(out["contract"]),
                                               encoding="utf-8")
    return out


# ---------------------------------------------------------------- graph

class GraphIn(BaseModel):
    graph: dict


@router.post("/media/graph/validate")
async def graph_validate(payload: GraphIn, user=Depends(get_current_user)):
    errs = validate_graph(payload.graph)
    return {"valid": errs == [], "diagnostics": errs,
            "node_types": sorted(NODE_DEFS),
            "note": "Fixed node registry only: no custom-node code is loaded."}


@router.post("/media/graph/run")
async def graph_run(payload: GraphIn, user=Depends(get_current_user)):
    """Execute a node graph through Sangam's existing engines only.

    Handlers: prompt/style_apply/text_chunk are pure text; tts uses
    the voice engine; image_generate uses the image engine;
    diagram_validate/subtitle_export/design_critique/overlay are the
    pure helpers. A missing engine fails with 503, never a fake.
    """
    from ..image_gen import generate_images
    from ..media_pipeline.audio import chunk_text, render_srt
    from ..voice import VoiceError, synthesize

    def _text(inputs: dict) -> dict:
        return {"text": inputs["text"]}

    def _style(inputs: dict) -> dict:
        from ..image_gen.styles import enhance_prompt
        positive, _neg = enhance_prompt(inputs["text"], inputs.get("style"))
        return {"text": positive}

    def _chunks(inputs: dict) -> dict:
        return {"chunks": [c["text"] for c in chunk_text(inputs["text"])]}

    def _tts(inputs: dict) -> dict:
        try:
            audio, mime = synthesize(inputs["text"])
        except VoiceError as exc:
            raise RuntimeError(str(exc)) from exc
        return {"audio": {"mime": mime, "bytes": len(audio)}}

    def _image(inputs: dict) -> dict:
        atts = generate_images(inputs["prompt"])
        return {"image": [a.model_dump(mode="json") for a in atts]}

    def _diagram(inputs: dict) -> dict:
        diags = validate_diagram(inputs["diagram"])
        return {"diagram": {"valid": diags == [], "diagnostics": diags}}

    def _subtitle(inputs: dict) -> dict:
        return {"text": render_srt(inputs["segments"])}

    def _critique(inputs: dict) -> dict:
        return {"text": json.dumps(critique_prototype(inputs["html"]))}

    def _overlay(inputs: dict) -> dict:
        return {"image": render_overlay_svg(inputs["annotations"])}

    handlers = {"prompt": _text, "style_apply": _style, "text_chunk": _chunks,
                "tts": _tts, "image_generate": _image,
                "diagram_validate": _diagram, "subtitle_export": _subtitle,
                "design_critique": _critique, "overlay": _overlay}
    try:
        return execute_graph(payload.graph, handlers)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ---------------------------------------------------------------- overlay/storyboard

class OverlayIn(BaseModel):
    annotations: list[dict]
    width: int = Field(default=1000, ge=1, le=4000)
    height: int = Field(default=1000, ge=1, le=4000)
    accent: str = "#3A7BD5"


@router.post("/media/overlay")
async def overlay_endpoint(payload: OverlayIn, user=Depends(get_current_user)):
    errs = validate_annotations(payload.annotations)
    if errs:
        raise HTTPException(status_code=422, detail=errs[0]["message"])
    return {"svg": render_overlay_svg(payload.annotations, payload.width,
                                      payload.height, payload.accent),
            "note": "Non-destructive overlay: the source image is untouched."}


class StoryboardIn(BaseModel):
    plan: dict


@router.post("/media/storyboard")
async def storyboard_endpoint(payload: StoryboardIn, user=Depends(get_current_user)):
    errs = validate_scene_plan(payload.plan)
    if errs:
        raise HTTPException(status_code=422, detail=errs[0]["message"])
    return {"stills": still_prompts(payload.plan),
            "note": "Still-image prompts only: no video or motion is rendered."}
