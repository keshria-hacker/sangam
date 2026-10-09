"""
api_routes/code_agent_routes.py — Code Agent (autonomous coding) endpoints.
Sangam-native; no external product names in the API.
"""
import json
from pathlib import Path

from fastapi import Depends
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import llm
from ..code_agent import CHAT_AGENT_TOOLS, run_agent, run_code_agent
from ..database import get_db
from .common import router


class CodeAgentIn(BaseModel):
    task: str
    model: str | None = None
    max_iterations: int = 12
    tdd_mode: bool = False


@router.post("/code-agent/run")
async def code_agent_run(payload: CodeAgentIn, db: AsyncSession = Depends(get_db)):
    """Run the Code Agent on a task. Streams SSE events: thought, tool_call, tool_result, done, error."""
    task = (payload.task or "").strip()
    if not task:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Task is required")

    model_id = payload.model or await llm.default_model_id(db)
    if not model_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="No model available")

    max_iter = max(1, min(int(payload.max_iterations or 12), 25))

    async def _stream():
        async for step in run_code_agent(task, model_id=model_id, db=db,
                                         max_iterations=max_iter,
                                         tdd_mode=payload.tdd_mode):
            data = {"kind": step.kind, "content": step.content}
            if step.tool_name:
                data["tool"] = step.tool_name
            yield f"data: {json.dumps(data)}\n\n"
        yield "data: {\"kind\": \"end\"}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


class ChatAgentIn(BaseModel):
    message: str
    model: str | None = None
    max_steps: int = 8
    tools: list[str] | None = None


@router.post("/agent/run")
async def chat_agent_run(payload: ChatAgentIn, db: AsyncSession = Depends(get_db)):
    """Chat Agent mode: tool-using loop. Streams SSE: thought, tool_call, tool_result, answer, done, error."""
    message = (payload.message or "").strip()
    if not message:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Message is required")

    model_id = payload.model or await llm.default_model_id(db)
    if not model_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="No model available")

    max_steps = max(1, min(int(payload.max_steps or 8), 15))
    # Only allow known-safe chat tools
    tool_names = [t for t in (payload.tools or CHAT_AGENT_TOOLS) if t in CHAT_AGENT_TOOLS]

    async def _stream():
        async for step in run_agent(message, model_id, db,
                                    tool_names=tool_names,
                                    max_iterations=max_steps):
            data = {"kind": step.kind, "content": step.content}
            if step.tool_name:
                data["tool"] = step.tool_name
            yield f"data: {json.dumps(data)}\n\n"
        yield "data: {\"kind\": \"end\"}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/designs/{project_id}/{filename:path}")
async def serve_design_file(project_id: str, filename: str):
    """Serve a generated design file for the sandboxed preview iframe."""
    from fastapi import HTTPException
    # Only allow safe project ids and html/css/js assets
    if not project_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="Bad project id")
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Bad filename")
    from ..tools.builtin import _get_workspace_root
    target = (_get_workspace_root() / "designs" / project_id / filename).resolve()
    root = (_get_workspace_root() / "designs").resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=403, detail="Outside designs root")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    media = "text/html" if target.suffix == ".html" else None
    return FileResponse(str(target), media_type=media)


class CodeMapIn(BaseModel):
    query: str  # 'explain' | 'path'
    target: str


@router.post("/code-agent/code-map")
async def code_agent_code_map(payload: CodeMapIn):
    """Direct code-map query (explain a symbol or trace A -> B)."""
    from ..tools.builtin import code_map_handler
    return await code_map_handler(payload.query, payload.target)
