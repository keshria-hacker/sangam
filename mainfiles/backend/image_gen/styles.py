"""
image_gen/styles.py — Fooocus-inspired style presets and prompt enhancement.

Fooocus's signature idea is "focus on prompting": styles expand a short
user prompt with quality/framing suffixes so the diffusion model gets a
well-formed prompt. These presets are Sangam's own take on that idea —
pure string manipulation, no model download, fully testable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageStyle:
    id: str
    name: str
    prompt_suffix: str
    negative_suffix: str = ""


STYLES: tuple[ImageStyle, ...] = (
    ImageStyle(
        id="none",
        name="No style",
        prompt_suffix="",
    ),
    ImageStyle(
        id="photographic",
        name="Photographic",
        prompt_suffix=(
            "photograph, ultra detailed, sharp focus, natural lighting, "
            "high resolution, professional photography"
        ),
        negative_suffix="cartoon, illustration, painting, blurry, low quality",
    ),
    ImageStyle(
        id="cinematic",
        name="Cinematic",
        prompt_suffix=(
            "cinematic shot, dramatic lighting, film still, shallow depth of "
            "field, 35mm, moody atmosphere"
        ),
        negative_suffix="blurry, low quality, amateur",
    ),
    ImageStyle(
        id="digital-art",
        name="Digital Art",
        prompt_suffix=(
            "digital artwork, highly detailed, vibrant colors, concept art, "
            "trending on artstation"
        ),
        negative_suffix="blurry, low quality, watermark",
    ),
    ImageStyle(
        id="anime",
        name="Anime",
        prompt_suffix="anime style, cel shaded, vibrant, detailed anime illustration",
        negative_suffix="photorealistic, blurry, low quality",
    ),
    ImageStyle(
        id="portrait",
        name="Portrait",
        prompt_suffix=(
            "portrait, 85mm lens, soft studio lighting, detailed skin texture, "
            "bokeh background"
        ),
        negative_suffix="deformed, blurry, low quality",
    ),
    ImageStyle(
        id="landscape",
        name="Landscape",
        prompt_suffix=(
            "breathtaking landscape, golden hour, epic scale, highly detailed, "
            "national geographic"
        ),
        negative_suffix="blurry, low quality",
    ),
    ImageStyle(
        id="fantasy",
        name="Fantasy",
        prompt_suffix=(
            "epic fantasy art, magical atmosphere, intricate details, "
            "ethereal lighting"
        ),
        negative_suffix="blurry, low quality, modern, photograph",
    ),
)

_STYLE_MAP = {s.id: s for s in STYLES}

# Shared quality floor appended to every styled prompt (Fooocus does the
# same via its default positive/negative prompt templates).
QUALITY_SUFFIX = "masterpiece, best quality, high detail"
QUALITY_NEGATIVE = "low quality, worst quality, blurry, watermark, text"


def get_style(style_id: str | None) -> ImageStyle:
    return _STYLE_MAP.get(style_id or "none", _STYLE_MAP["none"])


def list_styles() -> list[dict[str, str]]:
    return [{"id": s.id, "name": s.name} for s in STYLES]


def enhance_prompt(prompt: str, style_id: str | None = None) -> tuple[str, str]:
    """Return (positive_prompt, negative_prompt) with style applied."""
    prompt = (prompt or "").strip()
    style = get_style(style_id)
    positive = prompt
    if style.prompt_suffix:
        positive = f"{positive}, {style.prompt_suffix}" if positive else style.prompt_suffix
    if QUALITY_SUFFIX and positive:
        positive = f"{positive}, {QUALITY_SUFFIX}"
    negative_parts = [p for p in (style.negative_suffix, QUALITY_NEGATIVE) if p]
    negative = ", ".join(negative_parts)
    return positive, negative


# ---------------------------------------------------------------------------
# Fooocus prompt controls (pure string preprocessing, no model work)
#
# Prompt weights mirror Fooocus's token_weights() semantics from
# ldm_patched/modules/sd1_clip.py + patch_clip.py: (word) = x1.1, bare
# (word:1.3) = x1.3, nesting multiplies, so ((x)) = x1.21. The parsed
# weights are only honoured by an engine that does CLIP weighting
# (the local Fooocus engine); other engines get the plain text, and
# the service layer refuses weights there rather than silently
# dropping emphasis (see service.generate_images).
# Wildcards mirror Fooocus's apply_wildcards(): __name__ expands from a
# wordlist file, nesting is expanded breadth-first, and a missing file
# leaves the placeholder verbatim (never a silent empty string).
# ---------------------------------------------------------------------------

import random as _random
import re as _re

_WILDCARD_RE = _re.compile(r"__([\w-]+)__")
_WILDCARD_MAX_DEPTH = 8


def parse_prompt_weights(prompt: str) -> tuple[str, list[tuple[str, float]]]:
    """Parse ``(word)`` / ``(word:weight)`` groups.

    Returns (plain_text, segments) where plain_text has all parens and
    weight markers stripped and segments is a list of (text, weight)
    for every maximal run, weights rounded to 4 decimals. Text outside
    any group has weight 1.0. Unbalanced parens are treated as literal
    text (never crash on user input).
    """
    text = prompt or ""
    segments: list[tuple[str, float]] = []

    def emit(chunk: str, weight: float) -> None:
        if not chunk:
            return
        weight = round(weight, 4)
        if segments and segments[-1][1] == weight:
            segments[-1] = (segments[-1][0] + chunk, weight)
        else:
            segments.append((chunk, weight))

    # Simpler, correct-by-construction recursive parser:
    segments.clear()

    def parse_at(s: str, i: int, weight: float) -> int:
        """Parse s[i:] at the given inherited weight until ')' or end.
        Emits segments; returns the index just past ')' (or len(s))."""
        buf: list[str] = []
        j = i
        while j < len(s):
            ch = s[j]
            if ch == "(":
                if buf:
                    emit("".join(buf), weight)
                    buf = []
                # Find the matching ')' respecting nesting.
                depth = 1
                k = j + 1
                while k < len(s) and depth:
                    if s[k] == "(":
                        depth += 1
                    elif s[k] == ")":
                        depth -= 1
                    k += 1
                if depth:  # unbalanced: literal '('
                    buf.append(ch)
                    j += 1
                    continue
                inner = s[j + 1:k - 1]
                # Group weight: trailing :number, else 1.1 — but a
                # trailing :number inside a nested group belongs to
                # that group, not this one. Strip only if the suffix
                # is at nesting depth 0 of `inner`.
                group_weight, inner_text = _split_group_weight(inner)
                parse_at(inner_text, 0, weight * group_weight)
                j = k
            elif ch == ")":
                if buf:
                    emit("".join(buf), weight)
                return j + 1
            else:
                buf.append(ch)
                j += 1
        if buf:
            emit("".join(buf), weight)
        return j

    parse_at(text, 0, 1.0)
    plain = "".join(chunk for chunk, _ in segments)
    return plain, segments


def _split_group_weight(inner: str) -> tuple[float, str]:
    """Split 'word:1.3' -> (1.3, 'word'); 'word' -> (1.1, 'word').
    A trailing :number counts only when it sits at nesting depth 0."""
    depth = 0
    for idx in range(len(inner) - 1, -1, -1):
        ch = inner[idx]
        if ch == ")":
            depth += 1
        elif ch == "(":
            depth -= 1
        elif ch == ":" and depth == 0:
            tail = inner[idx + 1:].strip()
            if _re.fullmatch(r"-?\d+(?:\.\d+)?", tail):
                return float(tail), inner[:idx]
            break
    return 1.1, inner


def expand_wildcards(prompt: str, wildcards_dir=None, seed: int | None = None,
                     in_order: bool = False,
                     wordlists: dict[str, list[str]] | None = None) -> str:
    """Expand ``__name__`` placeholders.

    ``wildcards_dir`` is a directory of ``<name>.txt`` wordlists (one
    word per line, ``#`` comments ignored) — the Fooocus ``wildcards/``
    layout. ``wordlists`` is an in-memory equivalent (used by the API
    and by tests). With neither source, or a missing file, the
    placeholder is left verbatim. ``seed`` gives deterministic picks;
    ``in_order`` cycles through the list per placeholder name (batch
    consistency, as in Fooocus). Nesting is expanded breadth-first up
    to ``_WILDCARD_MAX_DEPTH`` passes.
    """
    from pathlib import Path

    rng = _random.Random(seed) if seed is not None else _random.Random()
    counters: dict[str, int] = {}
    wordlists = wordlists or {}

    def load(name: str) -> list[str] | None:
        if name in wordlists:
            return wordlists[name]
        if wildcards_dir is None:
            return None
        path = Path(wildcards_dir) / f"{name}.txt"
        try:
            words = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
                     if ln.strip() and not ln.strip().startswith("#")]
        except OSError:
            return None
        return words or None

    def pick(name: str) -> str | None:
        words = load(name)
        if not words:
            return None
        if in_order:
            idx = counters.get(name, 0)
            counters[name] = idx + 1
            return words[idx % len(words)]
        return rng.choice(words)

    current = prompt or ""
    for _ in range(_WILDCARD_MAX_DEPTH):
        if not _WILDCARD_RE.search(current):
            break

        def _sub(m):
            picked = pick(m.group(1))
            return picked if picked is not None else m.group(0)

        new = _WILDCARD_RE.sub(_sub, current)
        if new == current:
            break
        current = new
    return current


def prepare_prompt(prompt: str, wildcards_dir=None, seed: int | None = None,
                   in_order: bool = False,
                   wordlists: dict[str, list[str]] | None = None
                   ) -> tuple[str, str, list[tuple[str, float]]]:
    """Fooocus order: wildcards first, then weight parsing.

    Returns (expanded_raw, plain_text, weight_segments)."""
    expanded = expand_wildcards(prompt, wildcards_dir=wildcards_dir, seed=seed,
                                in_order=in_order, wordlists=wordlists)
    plain, segments = parse_prompt_weights(expanded)
    return expanded, plain, segments
