"""
Code Agent — autonomous coding agent (OpenHands-style patterns, Sangam-native).

The agent works in a loop:
1. Receives a task (e.g., "add rate limiting to the auth endpoints")
2. Inspects the workspace (list files, read code, search)
3. Plans and executes: writes/edits files, runs bash commands and tests
4. Observes results (stdout, errors, test output) and iterates
5. Stops when done or when max iterations reached

Tools: read_file, list_files, write_file, edit_file, run_bash,
        execute_code, web_search. All sandboxed to the workspace root.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

CODE_AGENT_SYSTEM = """You are Sangam's Code Agent, an autonomous software engineering agent.
You work in a loop: inspect the workspace, plan, act with tools, observe results, iterate.

Available tools:
- list_files(path, pattern): list files in the workspace
- read_file(path): read a file's contents
- write_file(path, content): create or overwrite a file
- edit_file(path, old_text, new_text): exact-match text replacement
- run_bash(command, timeout): run a shell command (tests, builds, git, etc.)
- execute_code(code, language): run a Python snippet
- web_search(query): search the web for docs/APIs

Rules:
1. Always inspect before acting — list files and read relevant code first.
2. Make small, verifiable changes. Run tests or builds after edits.
3. If a command fails, read the error and fix the cause — don't repeat blindly.
4. Never delete files unless the task explicitly asks.
5. When done, summarize what changed and how it was verified.
6. If blocked (missing credentials, ambiguous requirements), explain clearly and stop.
"""


@dataclass
class AgentStep:
    kind: str  # 'thought' | 'tool_call' | 'tool_result' | 'done' | 'error'
    content: str
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)


def _tools_schema() -> list[dict]:
    from .tools.registry import registry
    names = ["list_files", "read_file", "write_file", "edit_file",
             "run_bash", "execute_code", "web_search"]
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


async def run_code_agent(task: str, model: str | None = None,
                         max_iterations: int = 12, tdd_mode: bool = False):
    """Run the agent loop. Yields AgentStep events (for SSE streaming)."""
    import litellm
    from .instincts import get_relevant_instincts

    tools = _tools_schema()
    system = CODE_AGENT_SYSTEM
    instincts = get_relevant_instincts(task)
    if instincts:
        system += "\nLearned instincts (apply when relevant):\n" + "\n".join(
            f"- {i}" for i in instincts)
    if tdd_mode:
        system += ("\nTDD MODE: Write a failing test FIRST (RED), then implement "
                   "until it passes (GREEN), then refactor. Show test evidence.")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]

    # Resolve model
    if not model:
        model = "gpt-4o-mini"  # fallback; caller should pass the user's model

    yield AgentStep(kind="thought", content="Starting code agent…")

    for i in range(max_iterations):
        try:
            resp = await litellm.acompletion(
                model=model,
                messages=messages,
                tools=tools or None,
                tool_choice="auto" if tools else None,
            )
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
            yield AgentStep(kind="done", content=text or "Task complete.")
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

    yield AgentStep(kind="done", content="Reached max iterations. Stopping.")
