"""
Agent engine — autonomous tool-using loop (OpenHands-style, Sangam-native).

Generalized loop used by:
- Code Agent tab (`/api/code-agent/run`): code tools + CODE_AGENT_SYSTEM
- Chat Agent mode (`/api/agent/run`): user-selected tools + CHAT_AGENT_SYSTEM

The loop: plan → tool call → observe → answer, with max steps, stop support,
and per-step SSE streaming. All LLM calls go through Sangam's provider stack
(DB-encrypted keys, resolved per provider) — never bare litellm.
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
    from .tools.registry import registry
    tool = registry.get(name)
    if not tool or not tool.handler:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = await tool.handler(**args)
        return result if isinstance(result, dict) else {"result": result}
    except TypeError as exc:
        return {"error": f"Bad arguments for {name}: {exc}"}
    except Exception as exc:
        return {"error": f"{name} failed: {exc}"}


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


# In-memory approval gates: approval_id -> {event, decision}
_approval_gates: dict[str, dict] = {}

# Tools that require approval by default (user can customize via settings)
DEFAULT_APPROVAL_TOOLS = {"write_file", "edit_file", "run_bash", "execute_code"}


def create_approval_gate(approval_id: str) -> dict:
    """Create an approval gate. Returns {event, decision}."""
    import asyncio
    gate = {"event": asyncio.Event(), "decision": None}
    _approval_gates[approval_id] = gate
    return gate


def resolve_approval(approval_id: str, approved: bool) -> bool:
    """Resolve a pending approval. Returns True if the gate existed."""
    gate = _approval_gates.pop(approval_id, None)
    if not gate:
        return False
    gate["decision"] = approved
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
                    max_tools_per_run: int = 0):
    """Generalized agent loop. Yields AgentStep events for SSE streaming.

    Batch 5: at the START of the loop, skills are matched deterministically
    (match_skills) and fired skills' content is injected into the system
    prompt. Matching failures degrade silently (log line, run continues).
    max_tools_per_run (0 = unlimited) budgets fired skills + tool calls:
    firing stops once the budget is reached.
    """
    from .instincts import get_relevant_instincts

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

    total_tokens = 0
    tools_executed = 0
    for _ in range(max_iterations):
        # Budget check (rough: $0.01 per 1K tokens)
        if max_cost_usd > 0 and total_tokens * 0.01 / 1000 > max_cost_usd:
            yield AgentStep(kind="error",
                            content=f"Budget exceeded (${max_cost_usd:.2f}). Stopping.")
            return
        try:
            resp = await _llm_with_tools(model_id, messages, tools, db)
        except Exception as exc:
            yield AgentStep(kind="error", content=f"LLM call failed: {exc}")
            return

        msg = resp.choices[0].message
        text = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []
        # Rough token estimate
        total_tokens += len(text) // 4 + 100
        if on_usage:
            try:
                on_usage(total_tokens)
            except Exception:
                pass

        if text:
            yield AgentStep(kind="thought", content=text)
            messages.append({"role": "assistant", "content": text})

        if not tool_calls:
            yield AgentStep(kind="answer", content=text or "Done.")
            return

        for tc in tool_calls:
            # Batch 5 tool-count budget: fired skills + tools executed.
            if max_tools_per_run > 0 and len(fired_skills) + tools_executed >= max_tools_per_run:
                yield AgentStep(kind="error",
                                content=f"Tool budget exceeded ({max_tools_per_run}). Stopping.")
                return
            fname = tc["function"]["name"]
            try:
                fargs = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                fargs = {}
            # Approval gate for sensitive tools
            needs_approval = (require_approval is None and fname in DEFAULT_APPROVAL_TOOLS) or \
                             (require_approval is not None and fname in require_approval)
            if needs_approval:
                import asyncio, uuid
                approval_id = f"appr-{uuid.uuid4().hex[:12]}"
                gate = create_approval_gate(approval_id)
                yield AgentStep(kind="approval_needed",
                                content=f"Approval needed: {fname}({json.dumps(fargs)[:200]})",
                                tool_name=fname, tool_args=fargs,
                                approval_id=approval_id)
                try:
                    await asyncio.wait_for(gate["event"].wait(), timeout=approval_timeout)
                except asyncio.TimeoutError:
                    _approval_gates.pop(approval_id, None)
                    yield AgentStep(kind="error", content=f"Approval timed out for {fname} — skipped.")
                    messages.append({
                        "role": "tool", "tool_call_id": tc.get("id", ""), "name": fname,
                        "content": json.dumps({"error": "User did not approve in time. Tool skipped."}),
                    })
                    continue
                if not gate["decision"]:
                    yield AgentStep(kind="tool_result", content="Denied by user.",
                                    tool_name=fname)
                    messages.append({
                        "role": "tool", "tool_call_id": tc.get("id", ""), "name": fname,
                        "content": json.dumps({"error": "User denied this action."}),
                    })
                    continue
            yield AgentStep(kind="tool_call", content=f"{fname}({json.dumps(fargs)[:200]})",
                            tool_name=fname, tool_args=fargs)
            result = await _execute_tool(fname, fargs)
            tools_executed += 1
            result_str = json.dumps(result)[:8000]
            yield AgentStep(kind="tool_result", content=result_str,
                            tool_name=fname)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "name": fname,
                "content": result_str,
            })

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
