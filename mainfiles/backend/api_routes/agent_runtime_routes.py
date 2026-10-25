"""api_routes/agent_runtime_routes.py — Batch 10 runtime endpoints.

Registers onto the existing shared router (from api_routes/common.py),
so no main.py change is needed beyond the api.py import — same pattern
as Batch 9. All routes live under /api (authenticated, like the rest
of the shared router); paired LAN devices reach the approval tray
through their authenticated LAN session, the same session that serves
the rest of /api.

  POST /agent/runtime/plan            tool-call dependency planning (pi)
  POST /agent/runtime/contract        freeze a turn contract (odysseus)
  POST /agent/runtime/contract/check  check one tool against a contract
  POST /agent/runtime/compact         structured compaction + branch save
  GET  /agent/runtime/branches        list compaction branches
  POST /agent/runtime/branches/{id}/resume  resume a branch (child branch)
  POST /agent/runtime/runs/{id}/steer steer a run (message injected mid-run)
  POST /agent/runtime/runs/{id}/abort abort a run at the next step boundary
  GET  /agent/runtime/runs/{id}/steering  queued steering + abort state
  POST /agent/runtime/approvals/defer defer a risky call to the tray
  GET  /agent/runtime/approvals/tray   the 'Needs you' tray
  POST /agent/runtime/approvals/{id}/decide  decide (chat | paired-device)
  POST /agent/runtime/sandbox         preview (default) / create (confirm)
  POST /agent/runtime/sandbox/verify  preview (default) / run (confirm) gate
  POST /agent/runtime/flow            ticket graph: order + frontier
  POST /agent/runtime/hive/drain      inbox drain + critical-only escalation
  GET  /agent/runtime/drivers         supervised external runtimes (detect)
  POST /agent/runtime/eval/propose    propose a change from eval delta

Safety notes: sandbox creation and the verify gate run project code,
so both require confirm=true (preview otherwise, nothing executed).
Driver spawning is NOT exposed here — detection only — because an
arbitrary-command endpoint would be unrestricted execution.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ..agent_runtime.approval import CHANNEL
from ..agent_runtime.drivers import detect_all, detect_runtime
from ..agent_runtime.loop import (
    BranchStore,
    SteeringQueue,
    TurnContract,
    compact,
    plan_tool_calls,
)
from ..agent_runtime.orchestration import (
    TaskGraph,
    drain_inbox,
    escalate_critical_only,
    propose_from_eval,
)
from ..agent_runtime.sandbox import (
    default_execution_context,
    detect_test_command,
    run_verify_gate,
)
from .common import router

_BRANCHES = BranchStore()
_STEERING: dict[str, SteeringQueue] = {}


def _steering_for(run_id: str) -> SteeringQueue:
    return _STEERING.setdefault(run_id, SteeringQueue())


class PlanIn(BaseModel):
    tool_calls: list[dict] = Field(default_factory=list)


@router.post("/agent/runtime/plan")
async def runtime_plan(payload: PlanIn):
    try:
        groups = plan_tool_calls(payload.tool_calls)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"groups": [[{"id": c.id, "name": c.name, "reads": c.reads}
                        for c in group] for group in groups],
            "parallel_by_default": len(groups) <= 1}


class ContractIn(BaseModel):
    required: list[str] = Field(default_factory=list)
    offered: list[str] = Field(default_factory=list)
    executable: list[str] = Field(default_factory=list)


@router.post("/agent/runtime/contract")
async def runtime_contract(payload: ContractIn):
    try:
        contract = TurnContract(required=payload.required,
                                offered=payload.offered,
                                executable=payload.executable)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return contract.to_dict()


class ContractCheckIn(ContractIn):
    tool: str


@router.post("/agent/runtime/contract/check")
async def runtime_contract_check(payload: ContractCheckIn):
    try:
        contract = TurnContract(required=payload.required,
                                offered=payload.offered,
                                executable=payload.executable)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    status, detail = contract.check(payload.tool)
    return {"tool": payload.tool, "status": status, "detail": detail,
            "contract": contract.to_dict()}


class CompactIn(BaseModel):
    messages: list[dict] = Field(default_factory=list)
    read_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)


@router.post("/agent/runtime/compact")
async def runtime_compact(payload: CompactIn):
    summary = compact(payload.messages, read_files=payload.read_files,
                      modified_files=payload.modified_files)
    _BRANCHES.save(summary)
    return summary.to_dict()


@router.get("/agent/runtime/branches")
async def runtime_branches():
    return {"branches": _BRANCHES.list_branches()}


class ResumeIn(BaseModel):
    messages: list[dict] = Field(default_factory=list)
    read_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)


@router.post("/agent/runtime/branches/{branch_id}/resume")
async def runtime_resume(branch_id: str, payload: ResumeIn):
    try:
        child = _BRANCHES.resume(branch_id, new_messages=payload.messages,
                                 read_files=payload.read_files,
                                 modified_files=payload.modified_files)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return child.to_dict()


class SteerIn(BaseModel):
    message: str


@router.post("/agent/runtime/runs/{run_id}/steer")
async def runtime_steer(run_id: str, payload: SteerIn):
    try:
        queued = _steering_for(run_id).steer(payload.message)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"run_id": run_id, **queued}


class AbortIn(BaseModel):
    reason: str = ""


@router.post("/agent/runtime/runs/{run_id}/abort")
async def runtime_abort(run_id: str, payload: AbortIn):
    _steering_for(run_id).abort(payload.reason)
    return {"run_id": run_id, "aborted": True, "reason": payload.reason}


@router.get("/agent/runtime/runs/{run_id}/steering")
async def runtime_steering(run_id: str):
    queue = _steering_for(run_id)
    return {"run_id": run_id, "pending": queue.pending(),
            "aborted": queue.aborted, "abort_reason": queue.abort_reason}


class DeferIn(BaseModel):
    run_id: str = ""
    tool: str
    args: dict = Field(default_factory=dict)
    call_id: str = ""


@router.post("/agent/runtime/approvals/defer")
async def runtime_defer(payload: DeferIn):
    if not payload.tool:
        raise HTTPException(422, "tool is required")
    return CHANNEL.defer(payload.run_id, payload.tool, args=payload.args,
                         call_id=payload.call_id).to_dict()


@router.get("/agent/runtime/approvals/tray")
async def runtime_tray():
    return {"tray": CHANNEL.tray()}


class DecideIn(BaseModel):
    approved: bool
    source: str = "chat"
    reason: str = ""


@router.post("/agent/runtime/approvals/{approval_id}/decide")
async def runtime_decide(approval_id: str, payload: DecideIn):
    result = CHANNEL.decide(approval_id, payload.approved,
                            source=payload.source, reason=payload.reason)
    if not result.get("ok"):
        raise HTTPException(404 if "unknown" in result.get("error", "") else 422,
                            result["error"])
    return result


class SandboxIn(BaseModel):
    workspace: str
    run_id: str = "preview"
    confirm: bool = False


@router.post("/agent/runtime/sandbox")
async def runtime_sandbox(payload: SandboxIn):
    ws = Path(payload.workspace)
    if not ws.is_dir():
        raise HTTPException(422, f"workspace is not a directory: {payload.workspace}")
    if not payload.confirm:
        from ..agent_runtime.sandbox import _is_git_repo
        return {"mode": "preview", "executed": False,
                "would_create_worktree": _is_git_repo(ws),
                "workspace": str(ws),
                "detail": "Preview only: pass confirm=true to create the "
                          "per-run worktree (or fall back with a warning)."}
    return default_execution_context(ws, payload.run_id).to_dict()


class VerifyIn(BaseModel):
    workspace: str
    command: list[str] | None = None
    confirm: bool = False


@router.post("/agent/runtime/sandbox/verify")
async def runtime_verify(payload: VerifyIn):
    ws = Path(payload.workspace)
    if not ws.is_dir():
        raise HTTPException(422, f"workspace is not a directory: {payload.workspace}")
    detected = detect_test_command(ws)
    if not payload.confirm:
        return {"mode": "preview", "executed": False,
                "command": payload.command or detected["command"],
                "source": "caller-supplied" if payload.command else detected["source"],
                "detail": "Preview only: pass confirm=true to run the "
                          "project's own test command under the sandbox."}
    return run_verify_gate(ws, command=payload.command)


class FlowIn(BaseModel):
    tasks: list[dict] = Field(default_factory=list)


@router.post("/agent/runtime/flow")
async def runtime_flow(payload: FlowIn):
    try:
        graph = TaskGraph(payload.tasks)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {**graph.to_dict(), "execution_order": graph.execution_order(),
            "branch_review": graph.branch_review()}


class HiveIn(BaseModel):
    inbox: list[dict] = Field(default_factory=list)


@router.post("/agent/runtime/hive/drain")
async def runtime_hive_drain(payload: HiveIn):
    drained = drain_inbox(payload.inbox)
    escalation = escalate_critical_only(payload.inbox)
    return {"drained": drained["drained"], "remaining": drained["remaining"],
            "finished": drained["finished"],
            "handled_routine": len(escalation["handled"]),
            "escalated_critical": escalation["escalated"]}


@router.get("/agent/runtime/drivers")
async def runtime_drivers():
    return {"drivers": detect_all(),
            "note": "Detection only: spawning an external agent is a "
                    "host-operator library call, never an API request."}


@router.get("/agent/runtime/drivers/{name}/detect")
async def runtime_driver_detect(name: str):
    return detect_runtime(name)


class EvalProposeIn(BaseModel):
    eval_before: dict = Field(default_factory=dict)
    eval_after: dict = Field(default_factory=dict)
    change: dict = Field(default_factory=dict)


@router.post("/agent/runtime/eval/propose")
async def runtime_eval_propose(payload: EvalProposeIn):
    return propose_from_eval(payload.eval_before, payload.eval_after,
                             payload.change)
