"""api_routes/intelligence_routes.py — Auto response-intelligence API (A2).

POST /intelligence/route — dry-run the unified pipeline for debugging
and tests. No provider call, no DB write, no network: it returns the
routing decision (intent, resolved composer mode, Auto-chosen tools,
complexity, clarification question, blocked-video note, post-actions)
for a message plus optional history. The chat stream path runs the same
function (chat_stream_routes.py) — this endpoint and the live path
cannot drift apart because they share route_message().

POST /intelligence/harper — offline Harper-class lint suggestions for
a text. Suggestions only; nothing is rewritten or autocorrected, and
code fences / inline code / code-looking lines never produce issues.

Registered on the shared router by the single import in api.py.
"""
from __future__ import annotations

from fastapi import Depends
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..response_intelligence.pipeline import COMPOSER_MODES, TOOL_IDS, route_message
from ..response_quality.harper import lint_harper
from .common import router


class RouteIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    history: list[dict] = Field(default_factory=list)
    file_ids: list[str] = Field(default_factory=list)
    composer_mode: str = "auto"
    tool_overrides: dict[str, bool] = Field(default_factory=dict)
    adaptive_depth: bool = True


class HarperIn(BaseModel):
    text: str = Field(max_length=200_000)


@router.post("/intelligence/route")
async def intelligence_route(payload: RouteIn, user=Depends(get_current_user)):
    """Dry-run Auto routing. See module docstring; no side effects."""
    decision = route_message(
        payload.message,
        history=payload.history,
        file_ids=payload.file_ids,
        composer_mode=payload.composer_mode,
        tool_overrides=payload.tool_overrides,
        adaptive_depth=payload.adaptive_depth,
    )
    return decision.to_dict()


@router.post("/intelligence/harper")
async def intelligence_harper(payload: HarperIn, user=Depends(get_current_user)):
    """Offline lint suggestions (never rewrites, never autocorrects)."""
    return {"suggestions": lint_harper(payload.text)}


@router.get("/intelligence/modes")
async def intelligence_modes(user=Depends(get_current_user)):
    """Composer modes + tool vocabulary the pipeline understands."""
    return {"composer_modes": list(COMPOSER_MODES), "tools": list(TOOL_IDS)}
