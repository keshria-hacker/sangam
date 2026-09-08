"""
api_skills.py — REST endpoints for the skills/plug-in system.

Provides listing, detail, execution, chaining, and auto-suggest
endpoints consumed by the frontend Skills browser.
"""


from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.skills.registry import InvocationType, SkillCategory, get_registry
from backend.skills.router import get_router

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillExecuteRequest(BaseModel):
    skill_id: str
    params: dict = {}
    stream: bool = False


class SkillChainRequest(BaseModel):
    chain: list[dict]


@router.get("/")
async def list_skills(
    cat: str | None = None,
    inv: str | None = None,
    q: str | None = None,
):
    """List all registered skills, optionally filtered by category / invocation / search."""
    rg = get_registry()
    skills = list(rg.skills.values())

    if cat:
        skills = [s for s in skills if s.category.value == cat]
    if inv:
        skills = [s for s in skills if s.invocation.value in (inv, "both")]
    if q:
        skills = rg.search(q)

    return [
        {
            "id": s.id,
            "name": s.name,
            "cat": s.category.value,
            "inv": s.invocation.value,
            "desc": s.description,
            "tags": s.tags,
            "src": s.source_repo,
        }
        for s in skills
    ]


@router.get("/categories")
async def list_categories():
    """Return all known skill categories."""
    return [c.value for c in SkillCategory]


@router.get("/{sid}")
async def get_skill(sid: str):
    """Return full detail for a single skill, excluding the full prompt template."""
    rg = get_registry()
    sk = rg.get(sid)
    if not sk:
        raise HTTPException(404, f"Skill not found: {sid}")

    prompt = sk.prompt_template
    return {
        "id": sk.id,
        "name": sk.name,
        "cat": sk.category.value,
        "inv": sk.invocation.value,
        "desc": sk.description,
        "params": [
            {
                "n": p.name,
                "t": p.type,
                "d": p.description,
                "r": p.required,
                "def": p.default,
            }
            for p in sk.parameters
        ],
        "deps": sk.dependencies,
        "tags": sk.tags,
        "src": sk.source_repo,
        "prompt": (prompt[:500] + "...") if len(prompt) > 500 else prompt,
    }


@router.post("/execute")
async def execute_skill(r: SkillExecuteRequest):
    """Execute a single skill with the given parameters."""
    rt = get_router()
    ex = await rt.execute(r.skill_id, r.params, r.stream)
    if ex.error:
        raise HTTPException(500, ex.error)
    return {
        "id": ex.skill_id,
        "name": ex.skill_name,
        "result": ex.result,
        "duration_ms": ex.duration_ms,
    }


@router.post("/chain")
async def chain_skills(r: SkillChainRequest):
    """Execute a chain of skills sequentially."""
    rt = get_router()
    results = await rt.chain(r.chain)
    return {
        "results": [
            {
                "id": x.skill_id,
                "name": x.skill_name,
                "result": x.result,
                "error": x.error,
                "duration_ms": x.duration_ms,
            }
            for x in results
        ]
    }


@router.post("/auto-suggest")
async def suggest_skills(ctx: dict):
    """
    Given a conversation context dict, return auto-invocation and
    user-invocation skill suggestions ranked by relevance.
    """
    rg = get_registry()
    query = " ".join([
        ctx.get("last_user_message", ""),
        ctx.get("current_task", ""),
        " ".join(ctx.get("keywords", [])),
    ])
    matches = rg.search(query)

    auto = [s for s in matches if s.invocation in (InvocationType.AUTO, InvocationType.BOTH)]
    user = [s for s in matches if s.invocation == InvocationType.USER]

    return {
        "auto": [
            {"id": s.id, "name": s.name, "reason": f"Match: {query[:100]}"}
            for s in auto[:5]
        ],
        "user": [
            {"id": s.id, "name": s.name, "cat": s.category.value}
            for s in user[:10]
        ],
    }
