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
from dataclasses import dataclass, field
from typing import Any

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
    kind: str  # 'thought' | 'tool_call' | 'tool_result' | 'answer' | 'done' | 'error'
    content: str
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)


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


async def run_agent(task: str, model_id: str, db: Any,
                    tool_names: list[str] | None = None,
                    system_prompt: str = CHAT_AGENT_SYSTEM,
                    max_iterations: int = 8,
                    extra_system: str = ""):
    """Generalized agent loop. Yields AgentStep events for SSE streaming."""
    from .instincts import get_relevant_instincts

    tools = _tools_schema(tool_names or CHAT_AGENT_TOOLS)
    system = system_prompt
    instincts = get_relevant_instincts(task)
    if instincts:
        system += "\nLearned instincts (apply when relevant):\n" + "\n".join(
            f"- {i}" for i in instincts)
    if extra_system:
        system += "\n" + extra_system
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]

    yield AgentStep(kind="thought", content="Agent starting…")

    for _ in range(max_iterations):
        try:
            resp = await _llm_with_tools(model_id, messages, tools, db)
        except Exception as exc:
            yield AgentStep(kind="error", content=f"LLM call failed: {exc}")
            return

        msg = resp.choices[0].message
        text = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        if text:
            yield AgentStep(kind="thought", content=text)
            messages.append({"role": "assistant", "content": text})

        if not tool_calls:
            yield AgentStep(kind="answer", content=text or "Done.")
            return

        for tc in tool_calls:
            fname = tc["function"]["name"]
            try:
                fargs = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                fargs = {}
            yield AgentStep(kind="tool_call", content=f"{fname}({json.dumps(fargs)[:200]})",
                            tool_name=fname, tool_args=fargs)
            result = await _execute_tool(fname, fargs)
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
