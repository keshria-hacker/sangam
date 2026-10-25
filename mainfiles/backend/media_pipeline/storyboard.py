"""Scene plans + still-frame storyboards (manimgx + OpenMontage salvage).

ManimGX itself is a 3D *video* animation engine (Rust/wgpu, Manim-CE
API, MP4 output) — video, so excluded. Its portable, non-video salvage
is the scene description: a script broken into scenes with narration
and a still-frame description per scene. OpenMontage's shot-prompt
builder contributes the same shape for stills. This module validates a
scene plan and derives one *still-image* prompt per scene, which feeds
Sangam's existing image pipeline. No motion, no MP4, no renderer is
ever produced here — durations, where given, are labelled as plan
estimates, not rendered timing.
"""
from __future__ import annotations


def validate_scene_plan(plan: object) -> list[dict]:
    errs: list[dict] = []

    def err(code: str, message: str, fix: str) -> dict:
        return {"code": code, "message": message, "supportedFixes": fix}

    if not isinstance(plan, dict):
        return [err("not-an-object", "Scene plan must be an object",
                    "Pass {title, scenes: [...]}.")]
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return [err("no-scenes", "scenes must be a non-empty list",
                    "Add at least one scene with a still_description.")]
    for i, scene in enumerate(scenes):
        path = f"scenes[{i}]"
        if not isinstance(scene, dict):
            errs.append(err("bad-scene", f"{path} must be an object",
                            "Use {title, narration, still_description}."))
            continue
        if not (scene.get("still_description") or "").strip():
            errs.append(err("missing-still",
                            f"{path}.still_description is required",
                            "Describe the still frame for this scene — "
                            "this is what the image pipeline renders."))
        if not (scene.get("title") or "").strip():
            errs.append(err("missing-title", f"{path}.title is required",
                            "Give the scene a short title."))
        dur = scene.get("duration_seconds")
        if dur is not None and (not isinstance(dur, (int, float)) or dur <= 0):
            errs.append(err("bad-duration",
                            f"{path}.duration_seconds must be > 0 if given",
                            "Set a positive plan estimate, or omit it — "
                            "it is a plan label, not rendered timing."))
    return errs


def still_prompts(plan: dict) -> list[dict]:
    """One still-image prompt per scene (validated first)."""
    errs = validate_scene_plan(plan)
    if errs:
        raise ValueError(f"invalid scene plan: {errs[0]['message']}")
    out = []
    for scene in plan["scenes"]:
        beats = [b for b in (scene.get("beats") or []) if isinstance(b, str)]
        prompt = scene["still_description"].strip()
        if beats:
            prompt = f"{prompt} — {'; '.join(beats)}"
        out.append({"title": scene["title"], "narration": scene.get("narration", ""),
                    "image_prompt": prompt,
                    "duration_seconds_plan_estimate": scene.get("duration_seconds")})
    return out
