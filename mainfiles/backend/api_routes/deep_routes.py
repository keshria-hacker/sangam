"""api_routes/deep_routes.py — HTTP surface for the Wave-2 deep-read modules.

Thin authenticated wrappers only; all logic lives in the modules they
wrap (council_mode, teams/debate, hive, hook_monitor, phone_approval,
worktrees, skills/creator, skills/importer, persona_registry,
lesson_player). Importing this module registers the handlers on the
shared router (parent imports it from api.py).

Safety notes:
- Council/debate are reasoning-only (no tools, no approval conflict).
- Worktree repo/parent/run paths must resolve under the agent
  workspace root; commands run argv-only, never through a shell.
- Skill-creator drafts live under workspace/skill-drafts/<name> only;
  client-supplied paths are never honored.
- Phone tokens are good for exactly one approval decision, never
  account access (see phone_approval).
- Debate runs are bounded (<=8 personas, <=6 rounds) and run as a
  background job with a stop flag; the estimate endpoint must be
  called first so the UI can show cost before starting.
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import re
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..database import get_db
from .common import router


# ---------------------------------------------------------------- helpers
def _dump(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return str(obj)


def _workspace_root() -> Path:
    from ..tools.builtin import _get_workspace_root

    return _get_workspace_root()


def _contained(path: str | Path) -> Path:
    root = _workspace_root()
    cand = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    try:
        cand.relative_to(root)
    except ValueError:
        raise HTTPException(422, "Path must stay inside the workspace root.")
    return cand


async def _completer(db: Any, model: str | None):
    from ..llm import default_model_id, stream_completion

    model_id = model or await default_model_id(db)
    if not model_id:
        raise HTTPException(422, "No model configured.")

    async def complete(messages: list[dict[str, str]]) -> str:
        parts: list[str] = []
        async for chunk in stream_completion(model_id, messages, db, temperature=0.7):
            parts.append(chunk if isinstance(chunk, str) else (getattr(chunk, "text", None) or ""))
        return "".join(parts)

    return complete


def _hive_root() -> Path:
    root = Path(os.environ.get("SANGAM_HIVE_ROOT", "")) if os.environ.get("SANGAM_HIVE_ROOT") else _workspace_root() / "hive"
    return root


def _hive():
    from ..hive import Hive

    return Hive(_hive_root())


def _queue():
    from ..hook_monitor import ApprovalQueue

    return ApprovalQueue()


def _phone_store():
    from ..phone_approval import PhoneApprovalStore

    return PhoneApprovalStore()


def _breaker_state_path() -> Path:
    return _hive_root() / "breaker.json"


def _breaker_level(unhealthy: bool, reason: str) -> dict[str, Any]:
    import json

    from ..hive import Breaker

    path = _breaker_state_path()
    level = "healthy"
    hard_stop = False
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            level = raw.get("level", "healthy")
            hard_stop = bool(raw.get("hard_stop", False))
        except (json.JSONDecodeError, OSError):
            level = "healthy"
    breaker = Breaker(hard_stop=hard_stop, level=level)
    new_level = breaker.beat(unhealthy=unhealthy, reason=reason)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"level": new_level, "hard_stop": hard_stop,
                                "last_reason": reason,
                                "at": datetime.now(UTC).isoformat()}), encoding="utf-8")
    return {"level": new_level, "action": breaker.action, "stopped": breaker.stopped}


# ---------------------------------------------------------------- council
class DeliberateIn(BaseModel):
    question: str
    domain_seat: str | None = None
    model: str | None = None


@router.post("/teams/council/deliberate")
async def council_deliberate(payload: DeliberateIn, db: Any = Depends(get_db), user: Any = Depends(get_current_user)):
    from ..council_mode import OutcomeLedger, deliberate
    from ..teams.definitions import get_council_lenses

    try:
        lenses = get_council_lenses()
        result = await deliberate(payload.question, lenses, await _completer(db, payload.model),
                                  domain_seat=payload.domain_seat)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    # Persist the verdict + an outcome-ledger entry (kill criteria are
    # dated by the review date; the verdict text carries the detail).
    ledger = OutcomeLedger(_hive_root() / "outcomes.json")
    entry = ledger.record(prediction=result.verdict, owner=user.id,
                          review_date=(datetime.now(UTC) + timedelta(days=30)).date().isoformat(),
                          kill_criteria="See verdict text.")
    out = result.to_dict()
    out["consensus"] = result.tally.consensus
    out["split"] = not result.tally.consensus
    out["ledger_entry_id"] = entry.id
    return out


# ---------------------------------------------------------------- debate
class DebateEstimateIn(BaseModel):
    persona_count: int
    rounds: int
    cost_per_call_usd: float = 0.0


@router.post("/teams/debate/estimate")
async def debate_estimate(payload: DebateEstimateIn, user: Any = Depends(get_current_user)):
    from ..teams.debate import estimate_debate_cost

    try:
        return estimate_debate_cost(payload.persona_count, payload.rounds, payload.cost_per_call_usd).to_dict()
    except ValueError as exc:
        raise HTTPException(422, str(exc))


_DEBATE_JOBS: dict[str, dict[str, Any]] = {}


class DebateRunIn(BaseModel):
    topic: str
    persona_ids: list[str]
    rounds: int = 3
    model: str | None = None
    cost_per_call_usd: float = 0.0


async def _run_debate_job(job_id: str, payload: DebateRunIn, stop: threading.Event) -> None:
    from ..database import AsyncSessionLocal
    from ..persona_registry import load_personas
    from ..teams.debate import run_debate

    job = _DEBATE_JOBS[job_id]
    # Fresh session: the request-scoped db closes when the 202 returns.
    try:
        from types import SimpleNamespace

        personas = load_personas()
        selected = []
        for pid in payload.persona_ids:
            if pid not in personas:
                raise ValueError(f"Unknown persona: {pid}")
            p = personas[pid]
            # Debate reads slug/name/system_prompt; the registry stores
            # id/name/body — adapt instead of letting it fall back to a
            # generic "You are <name>." prompt and a dataclass repr.
            selected.append(SimpleNamespace(slug=p.id, name=p.name,
                                            system_prompt=p.body or p.description))
        async with AsyncSessionLocal() as db:
            completer = await _completer(db, payload.model)
            result = await run_debate(payload.topic, selected, payload.rounds, completer,
                                      coordinator_prompt=(
                                          "You are the debate coordinator. Synthesize the "
                                          "transcript so far into a fair summary, keeping "
                                          "disagreements visible rather than smoothing them away."),
                                      cost_per_call_usd=payload.cost_per_call_usd, stop_flag=stop)
        job["status"] = "done"
        job["result"] = _dump(result)
    except Exception as exc:  # job surface must never hang
        job["status"] = "failed"
        job["error"] = str(exc)


@router.post("/teams/debate/run", status_code=202)
async def debate_run(payload: DebateRunIn, db: Any = Depends(get_db), user: Any = Depends(get_current_user)):
    from ..persona_registry import load_personas
    from ..teams.debate import estimate_debate_cost

    if len(payload.persona_ids) > 8 or payload.rounds > 6:
        raise HTTPException(422, "Debate caps: at most 8 personas and 6 rounds; never silently trimmed.")
    try:
        estimate_debate_cost(len(payload.persona_ids), payload.rounds, payload.cost_per_call_usd)
        personas = load_personas()
        for pid in payload.persona_ids:
            if pid not in personas:
                raise HTTPException(422, f"Unknown persona: {pid}")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    job_id = f"deb-{uuid.uuid4().hex[:12]}"
    stop = threading.Event()
    _DEBATE_JOBS[job_id] = {"status": "running", "result": None, "error": None, "_stop": stop}
    asyncio.create_task(_run_debate_job(job_id, payload, stop))
    return {"job_id": job_id, "status": "running",
            "estimate": estimate_debate_cost(len(payload.persona_ids), payload.rounds,
                                             payload.cost_per_call_usd).to_dict()}


@router.get("/teams/debate/jobs/{job_id}")
async def debate_job(job_id: str, user: Any = Depends(get_current_user)):
    job = _DEBATE_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown debate job.")
    return {"job_id": job_id, "status": job["status"], "result": job["result"], "error": job["error"]}


@router.post("/teams/debate/jobs/{job_id}/stop")
async def debate_job_stop(job_id: str, user: Any = Depends(get_current_user)):
    job = _DEBATE_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown debate job.")
    job["_stop"].set()
    return {"job_id": job_id, "status": job["status"], "stopped": True}


# ---------------------------------------------------------------- hive
class HiveAgentIn(BaseModel):
    agent_id: str
    role: str
    cwd: str = ""
    session: str = ""
    identity: str = ""


class HiveMessageIn(BaseModel):
    sender: str
    recipient: str
    subject: str
    body: str
    reply_expected: bool = False
    broadcast: bool = False


@router.get("/teams/hive/agents")
async def hive_agents(user: Any = Depends(get_current_user)):
    hive = _hive()
    return {"agents": [_dump(a) for a in hive.load_registry().values()]}


@router.post("/teams/hive/agents", status_code=201)
async def hive_create_agent(payload: HiveAgentIn, user: Any = Depends(get_current_user)):
    hive = _hive()
    try:
        return _dump(hive.create_agent(payload.agent_id, payload.role, cwd=payload.cwd,
                                       session=payload.session, identity=payload.identity))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/teams/hive/agents/{agent_id}/archive")
async def hive_archive_agent(agent_id: str, user: Any = Depends(get_current_user)):
    hive = _hive()
    try:
        return _dump(hive.archive_agent(agent_id))
    except (ValueError, KeyError) as exc:
        raise HTTPException(404, str(exc))


@router.post("/teams/hive/messages", status_code=201)
async def hive_send_message(payload: HiveMessageIn, user: Any = Depends(get_current_user)):
    hive = _hive()
    return _dump(hive.send_message(payload.sender, payload.recipient, payload.subject, payload.body,
                                   reply_expected=payload.reply_expected, broadcast=payload.broadcast))


@router.get("/teams/hive/agents/{agent_id}/inbox")
async def hive_inbox(agent_id: str, user: Any = Depends(get_current_user)):
    hive = _hive()
    return {"messages": [_dump(m) for m in hive.inbox_messages(agent_id)]}


@router.get("/teams/hive/agents/{agent_id}/outbox")
async def hive_outbox(agent_id: str, user: Any = Depends(get_current_user)):
    hive = _hive()
    return {"messages": [_dump(m) for m in hive.outbox_messages(agent_id)]}


@router.post("/teams/hive/route")
async def hive_route(user: Any = Depends(get_current_user)):
    return _hive().route_messages()


@router.post("/teams/hive/closing")
async def hive_closing(user: Any = Depends(get_current_user)):
    return _dump(_hive().closing_time_broadcast())


@router.get("/teams/hive/closing/acks")
async def hive_acks(user: Any = Depends(get_current_user)):
    return _hive().collect_acks()


class BreakerBeatIn(BaseModel):
    unhealthy: bool
    reason: str = ""


@router.post("/teams/hive/breaker/beat")
async def hive_breaker_beat(payload: BreakerBeatIn, user: Any = Depends(get_current_user)):
    # Server-side tick: state persists in hive/breaker.json, never a browser timer.
    return _breaker_level(payload.unhealthy, payload.reason)


# ---------------------------------------------------------------- hook queue + phone approval
class HookDecideIn(BaseModel):
    approval_id: str
    decision: str


@router.get("/teams/hooks/queue")
async def hook_queue_list(user: Any = Depends(get_current_user)):
    queue = _queue()
    return {"pending": [_dump(q) for q in queue.pending()], "head": _dump(queue.head())}


@router.post("/teams/hooks/queue/decide")
async def hook_queue_decide(payload: HookDecideIn, user: Any = Depends(get_current_user)):
    result = _queue().decide(payload.approval_id, payload.decision)
    if not result.get("ok"):
        err = result.get("error", "Decision failed.")
        raise HTTPException(404 if "stale" in err or "empty" in err else 400, err)
    return result


class PhoneIssueIn(BaseModel):
    approval_id: str
    tool: str
    command_preview: str
    session_id: str = ""


@router.post("/teams/hooks/phone/issue")
async def phone_issue(payload: PhoneIssueIn, user: Any = Depends(get_current_user)):
    # The raw token is returned exactly once; only its hash is stored.
    return _phone_store().issue(payload.approval_id, payload.tool, payload.command_preview, payload.session_id)


class PhoneConsumeIn(BaseModel):
    token: str
    approval_id: str
    tool: str
    command_preview: str
    decision: str
    session_id: str = ""


@router.post("/teams/hooks/phone/consume")
async def phone_consume(payload: PhoneConsumeIn, user: Any = Depends(get_current_user)):
    consumed = _phone_store().consume(payload.token, payload.approval_id, payload.tool,
                                      payload.command_preview, payload.decision, payload.session_id)
    if not consumed.get("ok"):
        raise HTTPException(400, consumed.get("error", "Token consume failed."))
    # Apply through the normal queue path so the head (stale-click) guard still applies.
    decided = _queue().decide(payload.approval_id, payload.decision)
    if not decided.get("ok"):
        raise HTTPException(400, decided.get("error", "Queue decision failed."))
    return {"ok": True, "token": consumed, "queue": decided}


# ---------------------------------------------------------------- worktrees
class WorktreeCreateIn(BaseModel):
    repo: str
    name: str


class WorktreeRemoveIn(BaseModel):
    repo: str
    name: str


class WorktreeRunIn(BaseModel):
    path: str
    command: list[str]
    timeout: float = 120.0


class WorktreeAnnotateIn(BaseModel):
    diff_text: str
    comments: list[dict[str, Any]]


@router.get("/teams/worktrees")
async def worktree_list(repo: str, user: Any = Depends(get_current_user)):
    from ..worktrees import list_worktrees

    return {"worktrees": [_dump(w) for w in list_worktrees(_contained(repo))]}


@router.post("/teams/worktrees", status_code=201)
async def worktree_create(payload: WorktreeCreateIn, user: Any = Depends(get_current_user)):
    from ..worktrees import WorktreeError, create_worktree

    try:
        parent = _workspace_root() / "worktrees"
        return _dump(create_worktree(_contained(payload.repo), parent, payload.name))
    except (WorktreeError, ValueError) as exc:
        raise HTTPException(422, str(exc))


@router.post("/teams/worktrees/remove")
async def worktree_remove(payload: WorktreeRemoveIn, user: Any = Depends(get_current_user)):
    from ..worktrees import WorktreeError, remove_worktree

    try:
        parent = _workspace_root() / "worktrees"
        remove_worktree(_contained(payload.repo), parent, payload.name)
        return {"ok": True, "name": payload.name}
    except (WorktreeError, ValueError) as exc:
        raise HTTPException(422, str(exc))


@router.post("/teams/worktrees/run")
async def worktree_run(payload: WorktreeRunIn, user: Any = Depends(get_current_user)):
    from ..worktrees import WorktreeError, run_in_worktree

    try:
        return run_in_worktree(_contained(payload.path), payload.command, timeout=payload.timeout)
    except (WorktreeError, ValueError) as exc:
        raise HTTPException(422, str(exc))


@router.post("/teams/worktrees/annotate")
async def worktree_annotate(payload: WorktreeAnnotateIn, user: Any = Depends(get_current_user)):
    from ..worktrees import ReviewComment, annotate_diff

    try:
        comments = [ReviewComment(**c) for c in payload.comments]
        return annotate_diff(payload.diff_text, comments)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc))


# ---------------------------------------------------------------- skills: creator / import / personas
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _draft_dir(name: str) -> Path:
    if not _NAME_RE.match(name or ""):
        raise HTTPException(422, "Skill name must be alphanumeric, dash, or underscore.")
    return _workspace_root() / "skill-drafts" / name


class CreatorDraftIn(BaseModel):
    name: str
    description: str
    body: str
    category: str = "misc"
    invocation: str = "both"
    model_invocation: bool = True
    tags: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)


@router.post("/skills/creator/draft", status_code=201)
async def creator_draft(payload: CreatorDraftIn, user: Any = Depends(get_current_user)):
    from ..skills.creator import draft_skill

    path = draft_skill(_draft_dir(payload.name), payload.name, payload.description, payload.body,
                       category=payload.category, invocation=payload.invocation,
                       model_invocation=payload.model_invocation, tags=payload.tags, triggers=payload.triggers)
    return {"name": payload.name, "dir": str(path)}


class CreatorEvaluateIn(BaseModel):
    name: str
    test_prompts: list[dict[str, Any]]


@router.post("/skills/creator/evaluate")
async def creator_evaluate(payload: CreatorEvaluateIn, user: Any = Depends(get_current_user)):
    from ..skills.creator import evaluate_skill

    try:
        return evaluate_skill(_draft_dir(payload.name), payload.test_prompts)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class CreatorPublishIn(BaseModel):
    name: str
    eval_report: dict[str, Any]


@router.post("/skills/creator/publish")
async def creator_publish(payload: CreatorPublishIn, user: Any = Depends(get_current_user)):
    from ..skills.creator import publish_skill

    try:
        return publish_skill(_draft_dir(payload.name), payload.eval_report)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class ImportPreviewIn(BaseModel):
    owner: str
    repo: str
    skill: str
    ref: str = "main"


@router.post("/skills/import/preview")
async def import_preview(payload: ImportPreviewIn, user: Any = Depends(get_current_user)):
    from ..skills.importer import preview_curated_import

    try:
        return preview_curated_import(payload.owner, payload.repo, payload.skill, payload.ref)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Upstream fetch failed: {exc}")


class ImportInstallIn(BaseModel):
    preview: dict[str, Any]


@router.post("/skills/import/install")
async def import_install(payload: ImportInstallIn, user: Any = Depends(get_current_user)):
    from ..skills.importer import install_curated

    try:
        return install_curated(payload.preview)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Upstream fetch failed: {exc}")


@router.get("/skills/personas")
async def personas_list(user: Any = Depends(get_current_user)):
    from ..persona_registry import load_personas

    out = []
    for p in load_personas().values():
        d = _dump(p)
        d.pop("body", None)
        out.append(d)
    return {"personas": out}


@router.get("/skills/personas/suggest")
async def personas_suggest(task: str, user: Any = Depends(get_current_user)):
    from ..persona_registry import suggest_personas

    return {"suggestions": [_dump(p) for p in suggest_personas(task)]}


@router.get("/skills/personas/validate")
async def personas_validate(user: Any = Depends(get_current_user)):
    from ..persona_registry import validate_roster

    return validate_roster()


# ---------------------------------------------------------------- lessons
class LessonFromOutlineIn(BaseModel):
    topic: str
    outline: list[dict[str, Any]]


@router.post("/lessons/from-outline")
async def lesson_from_outline(payload: LessonFromOutlineIn, user: Any = Depends(get_current_user)):
    from ..lesson_player import lesson_from_outline

    try:
        return lesson_from_outline(payload.topic, payload.outline)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


_LESSON_PLAYERS: dict[str, Any] = {}


class LessonPlayerCreateIn(BaseModel):
    scenes: list[dict[str, Any]]


@router.post("/lessons/player", status_code=201)
async def lesson_player_create(payload: LessonPlayerCreateIn, user: Any = Depends(get_current_user)):
    from ..lesson_player import LessonPlayer, LessonScene

    try:
        player = LessonPlayer([LessonScene.from_dict(s) for s in payload.scenes])
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc))
    pid = f"les-{uuid.uuid4().hex[:12]}"
    _LESSON_PLAYERS[pid] = player
    return {"player_id": pid, "snapshot": player.snapshot()}


def _player(pid: str):
    player = _LESSON_PLAYERS.get(pid)
    if player is None:
        raise HTTPException(404, "Unknown lesson player.")
    return player


@router.get("/lessons/player/{player_id}")
async def lesson_player_get(player_id: str, user: Any = Depends(get_current_user)):
    return {"player_id": player_id, "snapshot": _player(player_id).snapshot()}


@router.post("/lessons/player/{player_id}/start")
async def lesson_player_start(player_id: str, user: Any = Depends(get_current_user)):
    return _player(player_id).start()


@router.post("/lessons/player/{player_id}/pause")
async def lesson_player_pause(player_id: str, user: Any = Depends(get_current_user)):
    return _player(player_id).pause()


@router.post("/lessons/player/{player_id}/resume")
async def lesson_player_resume(player_id: str, user: Any = Depends(get_current_user)):
    return _player(player_id).resume()


@router.post("/lessons/player/{player_id}/play-step")
async def lesson_player_step(player_id: str, user: Any = Depends(get_current_user)):
    return _player(player_id).play_step()


class LessonInterruptIn(BaseModel):
    question: str


@router.post("/lessons/player/{player_id}/interrupt")
async def lesson_player_interrupt(player_id: str, payload: LessonInterruptIn, user: Any = Depends(get_current_user)):
    return _player(player_id).interrupt(payload.question)


@router.post("/lessons/player/{player_id}/end-discussion")
async def lesson_player_end_discussion(player_id: str, user: Any = Depends(get_current_user)):
    return _player(player_id).end_discussion()


class LessonAnswerIn(BaseModel):
    answer: str


@router.post("/lessons/player/{player_id}/answer")
async def lesson_player_answer(player_id: str, payload: LessonAnswerIn, user: Any = Depends(get_current_user)):
    return _player(player_id).answer_question(payload.answer)
