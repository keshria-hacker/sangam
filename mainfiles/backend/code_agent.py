"""
Agent engine — autonomous tool-using loop (OpenHands-style, Sangam-native).

Generalized loop used by:
- Code Agent tab (`/api/code-agent/run`): code tools + CODE_AGENT_SYSTEM
- Chat Agent mode (`/api/agent/run`): user-selected tools + CHAT_AGENT_SYSTEM

The loop: plan → tool call → observe → answer, with max steps, stop support,
and per-step SSE streaming. All LLM calls go through Sangam's provider stack
(DB-encrypted keys, resolved per provider) — never bare litellm.

Deep-read Wave 1 (agent core) changes in this module:

* Tool arguments are parsed strictly: unparseable (possibly truncated)
  arguments FAIL the call — they never degrade to ``{}`` and execute.
  A ``length`` finish reason fails every tool call in that message.
* Every tool call passes the pi-style hook layer (``hooks.py``) via the
  tool executor, and the ECC risk-tier policy (``permission_policy.py``)
  in front of the approval gate: a blacklisted call is denied even
  under the ``automatic`` approval policy, with the rule cited.
* Approvals are durable: a DB row (``hooks.AgentApproval``) records
  pending/approved/denied/timeout with a reason. ``timeout`` and
  ``denied`` are distinct — a timeout is reported as a timeout, not a
  refusal. The in-memory gate (``_approval_gates``) is kept only as the
  live wait mechanism for the existing ``/agent/approve`` endpoint.
* Cost is real: per-response ``usage`` from LiteLLM is accumulated in
  :class:`CostMeter`. When a provider returns no usage, usage is
  recorded as unknown (never a fabricated estimate) and logged as such.
  A USD budget can only be enforced when usage is known and a price is
  configured; otherwise the run logs that the budget is unenforceable.
* Loop detection (ECC, 5 identical consecutive calls) stops the run
  and asks the user instead of burning iterations on retries.
* At a successful stop, the ECC Stop hook runs report-only batch
  checks over files the run touched; failures are reported, never
  auto-fixed.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


def _skill_field(skill: Any, field_name: str, default: Any = "") -> Any:
    if isinstance(skill, dict):
        return skill.get(field_name, default)
    return getattr(skill, field_name, default)


def match_skills(task: str, skills: Any, max_skills: int = 5) -> list[Any]:
    """Batch 5: deterministic skill matching for in-chat auto-invocation.

    No model call. Scores task text against declared trigger phrases
    (+10 per phrase present), skill-name words (+5), tags (+3), and
    description words (+1 each, words >= 4 chars). Skills scoring >= 5
    fire, best first. Accepts registry SkillDefinition objects or plain
    dicts (tests pass mocked dicts). USER-only skills never auto-fire.
    """
    text = (task or "").lower()
    words = set(re.findall(r"[a-z0-9]+", text))
    scored: list[tuple[int, Any]] = []
    for skill in skills or []:
        inv = str(_skill_field(skill, "invocation", "both"))
        inv = inv.rsplit(".", 1)[-1].lower()  # InvocationType.AUTO -> auto
        if inv == "user":
            continue
        score = 0
        for trigger in _skill_field(skill, "triggers", []) or []:
            if str(trigger).lower() in text:
                score += 10
        name = str(_skill_field(skill, "name", ""))
        for word in re.findall(r"[a-z0-9]+", name.lower()):
            if word in words:
                score += 5
        for tag in _skill_field(skill, "tags", []) or []:
            tag_text = str(tag).lower()
            if tag_text in words or tag_text in text:
                score += 3
        desc_words = {w for w in re.findall(r"[a-z0-9]+", str(_skill_field(skill, "description", "")).lower()) if len(w) >= 4}
        score += len(desc_words & words)
        if score >= 5:
            scored.append((score, skill))
    scored.sort(key=lambda item: -item[0])
    return [skill for _, skill in scored[:max_skills]]

CODE_AGENT_SYSTEM = """You are Sangam's Code Agent, an autonomous software engineering agent.
You work in a loop: inspect the workspace, plan, act with tools, observe results, iterate.

Rules:
1. Always inspect before acting — list files and read relevant code first.
2. Make small, verifiable changes. Run tests or builds after edits.
3. If a command fails, read the error and fix the cause — don't repeat blindly.
4. Never delete files unless the task explicitly asks.
5. When done, summarize what changed and how it was verified.
6. If blocked (missing credentials, ambiguous requirements), explain clearly and stop.
"""

CHAT_AGENT_SYSTEM = """You are Sangam's Agent, a helpful assistant that can use tools.
You work in a loop: think, call tools, observe results, then answer.

Rules:
1. Use tools when they help (search the web for current info, read files, run code).
2. Don't call tools for things you already know or that don't need them.
3. After gathering what you need, give a clear, direct answer.
4. If a tool fails, try a different approach or explain the limitation.
"""

CODE_AGENT_TOOLS = ["list_files", "read_file", "write_file", "edit_file",
                    "run_bash", "execute_code", "web_search", "code_map"]

CHAT_AGENT_TOOLS = ["web_search", "read_file", "list_files", "execute_code",
                    "code_map"]


@dataclass
class AgentStep:
    kind: str  # 'thought' | 'tool_call' | 'tool_result' | 'answer' | 'done' | 'error' | 'approval_needed'
    content: str
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    approval_id: str = ""


def _tools_schema(names: list[str]) -> list[dict]:
    from .tools.registry import registry
    out = []
    for name in names:
        tool = registry.get(name)
        if tool:
            out.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            })
    return out


async def _execute_tool(name: str, args: dict) -> dict:
    """Execute one tool via ToolExecutor (hook layer included).

    The executor's before-hooks (config protection, destructive-bash
    deny) run on every call, and same-file mutations are serialized.
    Returns the handler's dict unchanged when available, so the loop's
    tool messages keep their previous shape; failures become
    ``{"error": ...}`` dicts, as before.
    """
    from .hooks import default_guard_registry
    from .tools.executor import ToolExecutor
    from .tools.schemas import ToolCall
    import uuid as _uuid

    global _agent_executor
    if _agent_executor is None:
        # Handler-level timeouts still apply; the executor timeout is
        # only a backstop, so it is generous (previously there was none).
        _agent_executor = ToolExecutor(
            hooks=default_guard_registry(), default_timeout=300.0)
    result = await _agent_executor.execute(
        ToolCall(id=f"call-{_uuid.uuid4().hex[:12]}", name=name,
                 arguments=dict(args)))
    if isinstance(result.data, dict):
        return result.data
    if result.is_error:
        return {"error": result.error or result.content}
    return {"result": result.content}


_agent_executor = None


class ToolArgumentsError(ValueError):
    """Tool arguments could not be parsed, or were not an object.

    Raised instead of degrading to ``{}``: executing a call with
    invented empty arguments (pi's truncated-output footgun) is never
    acceptable.
    """


def parse_tool_arguments(raw: Any) -> dict:
    """Parse a tool call's arguments string strictly.

    Returns the parsed object, which must be a dict. Raises
    :class:`ToolArgumentsError` on unparseable JSON, non-object JSON,
    or a non-string input — the caller must fail the call and tell the
    model to re-issue it with complete arguments.
    """
    if not isinstance(raw, str):
        raise ToolArgumentsError(
            f"Tool arguments are not a string (got {type(raw).__name__}). "
            "Re-issue the call with complete JSON arguments.")
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ToolArgumentsError(
            f"Tool arguments could not be parsed ({exc}); the output may "
            "have been truncated. Do NOT execute with partial arguments — "
            "re-issue the call with complete arguments.") from exc
    if not isinstance(parsed, dict):
        raise ToolArgumentsError(
            "Tool arguments must be a JSON object. Re-issue the call with "
            "complete object arguments.")
    return parsed


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from a dict-like or attribute-style LLM object."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(name, default)
        except Exception:  # noqa: BLE001
            pass
    return getattr(obj, name, default)


def extract_usage(resp: Any) -> dict[str, int] | None:
    """Extract real provider usage from a LiteLLM response, or None.

    Accepts attribute-style (``resp.usage.prompt_tokens``) and
    dict-style usage. Returns None when the provider returned no usable
    usage — the caller records that as unknown, never estimates it.
    """
    usage = getattr(resp, "usage", None)
    if usage is None and isinstance(resp, dict):
        usage = resp.get("usage")
    if usage is None:
        return None
    prompt = _field(usage, "prompt_tokens")
    completion = _field(usage, "completion_tokens")
    total = _field(usage, "total_tokens")
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    if total is None:
        return None
    try:
        return {
            "prompt_tokens": int(prompt or 0),
            "completion_tokens": int(completion or 0),
            "total_tokens": int(total),
        }
    except (TypeError, ValueError):
        return None


class CostMeter:
    """Real per-run cost accounting from provider usage objects.

    No flat-rate formula, no ``len(text)//4`` estimate. ``cost_usd``
    is None unless a price per 1K tokens is configured — an unknown
    cost is reported as unknown, not fabricated from a made-up rate.
    """

    def __init__(self, price_per_1k_usd: float | None = None):
        self.price_per_1k_usd = price_per_1k_usd
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.responses = 0
        self.unknown_responses = 0

    def add(self, usage: dict[str, int] | None) -> bool:
        """Accumulate one response's usage. Returns True when known."""
        self.responses += 1
        if usage is None:
            self.unknown_responses += 1
            logger.warning(
                "provider returned no usage for a response; usage "
                "recorded as unknown (no estimate substituted)")
            return False
        self.prompt_tokens += usage.get("prompt_tokens", 0)
        self.completion_tokens += usage.get("completion_tokens", 0)
        self.total_tokens += usage.get("total_tokens", 0)
        return True

    @property
    def usage_known(self) -> bool:
        return self.unknown_responses == 0 and self.responses > 0

    @property
    def cost_usd(self) -> float | None:
        if self.price_per_1k_usd is None:
            return None
        return self.total_tokens * self.price_per_1k_usd / 1000.0

    def budget_exceeded(self, max_cost_usd: float) -> bool | None:
        """True when over budget, False when within, None when the
        cost cannot be determined (unknown usage or no price)."""
        cost = self.cost_usd
        if cost is None:
            return None
        return cost > max_cost_usd

    def snapshot(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "responses": self.responses,
            "unknown_responses": self.unknown_responses,
            "usage_known": self.usage_known,
            "cost_usd": self.cost_usd,
            "cost_known": self.cost_usd is not None,
        }


async def _llm_with_tools(model_id: str, messages: list[dict],
                          tools: list[dict], db: Any):
    """Call the model with tools via Sangam's provider stack (DB keys)."""
    import litellm
    from .providers.key_resolver import resolve_api_key
    from .providers import _resolve_model

    provider_id, litellm_id = _resolve_model(model_id)
    api_key = await resolve_api_key(provider_id, db)
    if not api_key:
        raise RuntimeError(f"No API key configured for provider '{provider_id}'")
    return await litellm.acompletion(
        model=litellm_id,
        messages=messages,
        tools=tools or None,
        tool_choice="auto" if tools else None,
        api_key=api_key,
    )


# In-memory approval gates: approval_id -> {event, decision, reason}.
# This dict is ONLY the live wait mechanism for the /agent/approve
# endpoint. The durable record is the AgentApproval DB row (hooks.py),
# written and transitioned by run_agent; a restart loses the wait, but
# never the decision history.
_approval_gates: dict[str, dict] = {}

# Tools that require approval by default (user can customize via settings)
DEFAULT_APPROVAL_TOOLS = {"write_file", "edit_file", "run_bash", "execute_code"}


def create_approval_gate(approval_id: str) -> dict:
    """Create an approval gate. Returns {event, decision, reason}."""
    import asyncio
    gate = {"event": asyncio.Event(), "decision": None, "reason": None}
    _approval_gates[approval_id] = gate
    return gate


def resolve_approval(approval_id: str, approved: bool,
                     reason: str | None = None) -> bool:
    """Resolve a pending approval. Returns True if the gate existed.

    ``reason`` is the denial reason when denying; it is stored on the
    gate and persisted to the DB row by the waiting loop. The existing
    two-argument call shape (used by /agent/approve) keeps working.
    """
    gate = _approval_gates.pop(approval_id, None)
    if not gate:
        return False
    gate["decision"] = approved
    gate["reason"] = reason
    gate["event"].set()
    return True


async def run_agent(task: str, model_id: str, db: Any,
                    tool_names: list[str] | None = None,
                    system_prompt: str = CHAT_AGENT_SYSTEM,
                    max_iterations: int = 8,
                    extra_system: str = "",
                    require_approval: list[str] | None = None,
                    approval_timeout: float = 120.0,
                    max_cost_usd: float = 0.0,
                    on_usage: Any = None,
                    max_tools_per_run: int = 0,
                    approval_policy: str = "default",
                    price_per_1k_usd: float | None = None,
                    on_usage_detail: Any = None,
                    stop_check_budget_s: float = 120.0):
    """Generalized agent loop. Yields AgentStep events for SSE streaming.

    Batch 5: at the START of the loop, skills are matched deterministically
    (match_skills) and fired skills' content is injected into the system
    prompt. Matching failures degrade silently (log line, run continues).
    max_tools_per_run (0 = unlimited) budgets fired skills + tool calls:
    firing stops once the budget is reached.

    Wave 1: ``approval_policy`` ("default" | "automatic" | "always_ask")
    is evaluated through the risk-tier policy on every call; a
    blacklisted call is denied even under "automatic". ``on_usage``
    receives the real total token count, or None when the provider
    returned no usage; ``on_usage_detail`` (when given) receives the
    full CostMeter snapshot. ``price_per_1k_usd`` enables USD budget
    enforcement; without it (or without usage) a budget is logged as
    unenforceable, never enforced on a fabricated number.
    """
    from .hooks import (LoopDetector, format_stop_report,
                        record_approval_row, run_stop_checks,
                        transition_approval_row)
    from .instincts import get_relevant_instincts
    from .permission_policy import DEFAULT_POLICY

    tools = _tools_schema(tool_names or CHAT_AGENT_TOOLS)
    system = system_prompt
    instincts = get_relevant_instincts(task)
    if instincts:
        system += "\nLearned instincts (apply when relevant):\n" + "\n".join(
            f"- {i}" for i in instincts)
    # Batch 5 auto-invocation (failures never break the run).
    fired_skills: list[Any] = []
    try:
        from .skills.registry import get_registry
        all_skills = list(get_registry().skills.values())
        budget_for_skills = max_tools_per_run if max_tools_per_run > 0 else 5
        fired_skills = match_skills(task, all_skills, max_skills=budget_for_skills)
    except Exception as exc:  # noqa: BLE001 — degrade silently
        logger.warning("skill auto-invocation failed: %s", exc)
        fired_skills = []
    if fired_skills:
        chunks = []
        for skill in fired_skills:
            prompt = _skill_field(skill, "prompt_template", "") or ""
            chunks.append(f"## {_skill_field(skill, 'name', 'skill')}\n{prompt[:2000]}")
        system += ("\nAuto-invoked skills (follow when relevant):\n"
                   + "\n\n".join(chunks))
    if extra_system:
        system += "\n" + extra_system
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]

    yield AgentStep(kind="thought", content="Agent starting…")
    if fired_skills:
        yield AgentStep(
            kind="thought",
            content="Auto-invoked skills: " + ", ".join(
                str(_skill_field(s, "name", "?")) for s in fired_skills))

    tools_executed = 0
    meter = CostMeter(price_per_1k_usd=price_per_1k_usd)
    loop_detector = LoopDetector()
    touched_files: list[str] = []
    budget_warned = False

    def _stop_report_step() -> AgentStep | None:
        if not touched_files:
            return None
        try:
            report = format_stop_report(
                run_stop_checks(touched_files, budget_s=stop_check_budget_s))
        except Exception as exc:  # noqa: BLE001 — Stop hook never breaks a run
            logger.warning("Stop hook failed: %s", exc)
            return None
        if not report:
            return None
        return AgentStep(kind="thought", content=report)

    for _ in range(max_iterations):
        # Real budget check: only enforceable when cost is known.
        if max_cost_usd > 0:
            exceeded = meter.budget_exceeded(max_cost_usd)
            if exceeded is True:
                yield AgentStep(kind="error",
                                content=f"Budget exceeded (${max_cost_usd:.2f}). Stopping.")
                return
            if exceeded is None and not budget_warned:
                budget_warned = True
                logger.warning(
                    "cost budget $%.2f cannot be enforced: provider usage "
                    "unknown or no price per 1K tokens configured; "
                    "continuing without a USD budget check", max_cost_usd)
        try:
            resp = await _llm_with_tools(model_id, messages, tools, db)
        except Exception as exc:
            yield AgentStep(kind="error", content=f"LLM call failed: {exc}")
            return

        choice = resp.choices[0]
        msg = _field(choice, "message", {}) or {}
        text = _field(msg, "content") or ""
        tool_calls = _field(msg, "tool_calls") or []
        finish_reason = _field(choice, "finish_reason")
        # Real provider usage — never the old len(text)//4 estimate.
        latest_known = meter.add(extract_usage(resp))
        if on_usage:
            try:
                # Cumulative real tokens, or None when the latest
                # response carried no usage (unknown, not zero).
                on_usage(meter.total_tokens if latest_known else None)
            except Exception:
                pass
        if on_usage_detail:
            try:
                on_usage_detail(meter.snapshot())
            except Exception:
                pass

        if text:
            yield AgentStep(kind="thought", content=text)
            messages.append({"role": "assistant", "content": text})

        if not tool_calls:
            yield AgentStep(kind="answer", content=text or "Done.")
            step = _stop_report_step()
            if step is not None:
                yield step
            return

        # Truncated output is poison (pi): a `length` finish reason means
        # arguments may be corrupt, so fail every call — never execute.
        if finish_reason == "length":
            yield AgentStep(
                kind="error",
                content="Model output was truncated (length limit); tool "
                        "calls from this message were NOT executed because "
                        "their arguments may be corrupt. Re-issue them.")
            for tc in tool_calls:
                fname = _field(_field(tc, "function", {}), "name", "")
                messages.append({
                    "role": "tool",
                    "tool_call_id": _field(tc, "id", ""),
                    "name": fname,
                    "content": json.dumps({"error": "Tool call not executed: "
                        "model output was truncated; re-issue the call with "
                        "complete arguments."}),
                })
            continue

        for tc in tool_calls:
            # Batch 5 tool-count budget: fired skills + tools executed.
            if max_tools_per_run > 0 and len(fired_skills) + tools_executed >= max_tools_per_run:
                yield AgentStep(kind="error",
                                content=f"Tool budget exceeded ({max_tools_per_run}). Stopping.")
                return
            fn = _field(tc, "function", {}) or {}
            fname = _field(fn, "name", "")
            raw_args = _field(fn, "arguments") or "{}"
            try:
                fargs = parse_tool_arguments(raw_args)
            except ToolArgumentsError as exc:
                # Never execute with degraded {} arguments.
                yield AgentStep(kind="error",
                                content=f"Tool call to {fname} NOT executed: {exc}")
                messages.append({
                    "role": "tool", "tool_call_id": _field(tc, "id", ""),
                    "name": fname,
                    "content": json.dumps({"error": str(exc)}),
                })
                loop_detector.record(fname, {"_unparseable": str(raw_args)[:200]})
                continue
            # Loop detection: 5 identical consecutive calls stop the run
            # and ask the user — never auto-retry with a new strategy.
            if loop_detector.record(fname, fargs):
                yield AgentStep(
                    kind="error",
                    content=f"Loop detected: {fname} with identical "
                            f"arguments was called {loop_detector.threshold} "
                            "times in a row. Stopping and awaiting user "
                            "direction instead of retrying.")
                return
            # Risk-tier policy in front of the approval gate. A blacklist
            # denial wins even under the automatic policy, with the rule
            # cited; the call is never executed and never gated.
            decision = DEFAULT_POLICY.evaluate(
                fname, fargs, approval_policy=approval_policy,
                require_approval=require_approval)
            if decision.decision == "deny":
                detail = {"error": decision.reason}
                if decision.rule_id:
                    detail["rule"] = decision.rule_id
                if decision.recovery_hint:
                    detail["recovery_hint"] = decision.recovery_hint
                yield AgentStep(kind="tool_result",
                                content=f"Denied by policy"
                                        f" ({decision.rule_id}): {decision.reason}"
                                        + (f" {decision.recovery_hint}"
                                           if decision.recovery_hint else ""),
                                tool_name=fname)
                messages.append({
                    "role": "tool", "tool_call_id": _field(tc, "id", ""),
                    "name": fname,
                    "content": json.dumps(detail),
                })
                continue
            needs_approval = decision.decision == "ask"
            if needs_approval:
                import asyncio, uuid
                approval_id = f"appr-{uuid.uuid4().hex[:12]}"
                gate = create_approval_gate(approval_id)
                if db is not None:
                    await record_approval_row(db, approval_id, fname, fargs)
                yield AgentStep(kind="approval_needed",
                                content=f"Approval needed: {fname}({json.dumps(fargs)[:200]})",
                                tool_name=fname, tool_args=fargs,
                                approval_id=approval_id)
                try:
                    await asyncio.wait_for(gate["event"].wait(), timeout=approval_timeout)
                except asyncio.TimeoutError:
                    _approval_gates.pop(approval_id, None)
                    if db is not None:
                        await transition_approval_row(
                            db, approval_id, "timeout",
                            f"Approval timed out after {approval_timeout}s "
                            "(not a refusal)")
                    yield AgentStep(kind="error", content=f"Approval timed out for {fname} (not a refusal) — skipped.")
                    messages.append({
                        "role": "tool", "tool_call_id": _field(tc, "id", ""), "name": fname,
                        "content": json.dumps({"error": "Approval timed out (not a refusal). Tool skipped."}),
                    })
                    continue
                if not gate["decision"]:
                    reason = gate.get("reason") or "denied by user"
                    if db is not None:
                        await transition_approval_row(
                            db, approval_id, "denied", reason)
                    yield AgentStep(kind="tool_result",
                                    content=f"Denied by user: {reason}",
                                    tool_name=fname)
                    messages.append({
                        "role": "tool", "tool_call_id": _field(tc, "id", ""), "name": fname,
                        "content": json.dumps({"error": f"User denied this action: {reason}"}),
                    })
                    continue
                if db is not None:
                    await transition_approval_row(db, approval_id, "approved")
            yield AgentStep(kind="tool_call", content=f"{fname}({json.dumps(fargs)[:200]})",
                            tool_name=fname, tool_args=fargs)
            result = await _execute_tool(fname, fargs)
            tools_executed += 1
            if fname in ("write_file", "edit_file") and result.get("ok"):
                path = fargs.get("path")
                if isinstance(path, str) and path:
                    touched_files.append(path)
            result_str = json.dumps(result, default=str)[:8000]
            yield AgentStep(kind="tool_result", content=result_str,
                            tool_name=fname)
            messages.append({
                "role": "tool",
                "tool_call_id": _field(tc, "id", ""),
                "name": fname,
                "content": result_str,
            })

    step = _stop_report_step()
    if step is not None:
        yield step
    yield AgentStep(kind="done", content="Reached max steps. Stopping.")


async def run_code_agent(task: str, model_id: str, db: Any,
                         max_iterations: int = 12, tdd_mode: bool = False):
    """Code Agent loop (tab). Yields AgentStep events."""
    extra = ""
    if tdd_mode:
        extra = ("TDD MODE: Write a failing test FIRST (RED), then implement "
                 "until it passes (GREEN), then refactor. Show test evidence.")
    async for step in run_agent(
        task, model_id, db,
        tool_names=CODE_AGENT_TOOLS,
        system_prompt=CODE_AGENT_SYSTEM,
        max_iterations=max_iterations,
        extra_system=extra,
    ):
        # Map 'answer' to 'done' for the code-agent UI
        if step.kind == "answer":
            yield AgentStep(kind="done", content=step.content)
        else:
            yield step
