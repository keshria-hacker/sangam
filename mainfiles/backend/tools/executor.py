"""Tool executor for running tool calls.

Pi-style hook layer (see ``hooks.py``): every call passes
``before_tool_call`` (may block with a reason — a blocked call never
executes) and ``after_tool_call`` (may rewrite/redact the result).
Hooks are opt-in on the shared ``executor`` instance so existing
callers (e.g. the provider tool path) keep their current behaviour;
the agent loop builds its own executor with the ECC guard hooks.

Same-file mutations are serialized per resolved path argument (pi's
file-mutation-queue semantics, via one ``asyncio.Lock`` per path), so
two parallel writes to one file cannot interleave.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .registry import ToolRegistry, registry
from .schemas import ToolCall, ToolResult

logger = logging.getLogger(__name__)

# Tools whose handler mutates a file identified by a `path` argument.
_MUTATING_FILE_TOOLS = frozenset({"write_file", "edit_file"})


class ToolExecutionError(Exception):
    def __init__(self, message: str, tool_name: str | None = None, tool_call_id: str | None = None):
        super().__init__(message)
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id


class ToolTimeoutError(ToolExecutionError):
    pass


class ToolValidationError(ToolExecutionError):
    pass


class ToolExecutor:
    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        default_timeout: float = 30.0,
        max_result_size: int = 100000,
        hooks: Any = None,
    ):
        self.registry = tool_registry or registry
        self.default_timeout = default_timeout
        self.max_result_size = max_result_size
        self._active_tasks = {}
        # HookRegistry from ..hooks, or None for the legacy behaviour.
        self.hooks = hooks
        self._mutation_locks: dict[str, asyncio.Lock] = {}

    def _mutation_lock(self, tool_name: str, arguments: dict) -> asyncio.Lock | None:
        if tool_name not in _MUTATING_FILE_TOOLS:
            return None
        path = arguments.get("path")
        if not isinstance(path, str) or not path:
            return None
        lock = self._mutation_locks.get(path)
        if lock is None:
            lock = asyncio.Lock()
            self._mutation_locks[path] = lock
        return lock

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute one call: before-hooks, then the handler, then after-hooks.

        After-hooks run on every returned result (success, validation
        error, timeout, handler error, hook block) so redaction can
        never be bypassed by the failure path. Cancellation still
        propagates as an exception.
        """
        result = await self._execute_inner(tool_call)
        if self.hooks is not None:
            from ..hooks import HookedResult
            hooked = HookedResult(
                content=result.content, data=result.data,
                is_error=result.is_error, error=result.error)
            hooked = await self.hooks.run_after(
                tool_call.name, dict(tool_call.arguments), hooked)
            result = ToolResult(
                tool_call_id=result.tool_call_id, name=result.name,
                content=hooked.content, data=hooked.data,
                is_error=hooked.is_error, error=hooked.error)
        return result

    async def _execute_inner(self, tool_call: ToolCall) -> ToolResult:
        start_time = time.time()
        tool_def = self.registry.get(tool_call.name)

        # Hook point 1 — before_tool_call, consulted on EVERY call,
        # including calls to unknown tools (a guard may deny by pattern).
        if self.hooks is not None:
            decision = await self.hooks.run_before(
                tool_call.name, dict(tool_call.arguments))
            if decision.block:
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=f"Error: Blocked by hook: {decision.reason}",
                    error=decision.reason,
                    is_error=True,
                )

        if not tool_def:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Error: Unknown tool '{tool_call.name}'",
                error=f"Unknown tool: {tool_call.name}",
                is_error=True,
            )

        if not self.registry.is_enabled(tool_call.name):
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Error: Tool '{tool_call.name}' is disabled",
                error=f"Tool disabled: {tool_call.name}",
                is_error=True,
            )

        valid, error = self._validate_arguments(tool_def, tool_call.arguments)
        if not valid:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Error: Invalid arguments - {error}",
                error=f"Validation error: {error}",
                is_error=True,
            )

        if not tool_def.handler:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Error: Tool '{tool_call.name}' has no handler",
                error=f"No handler for tool: {tool_call.name}",
                is_error=True,
            )

        try:
            lock = self._mutation_lock(tool_call.name, tool_call.arguments)
            if lock is not None:
                async with lock:
                    result = await self._execute_with_timeout(
                        tool_def.handler, tool_call.arguments)
            else:
                result = await self._execute_with_timeout(tool_def.handler, tool_call.arguments)
            duration = time.time() - start_time
            logger.info(f"Tool '{tool_call.name}' executed in {duration:.2f}s")

            # Check if handler returned an error dict
            is_handler_error = isinstance(result, dict) and "error" in result
            content = str(result)
            if len(content) > self.max_result_size:
                content = content[:self.max_result_size] + f"\n... [truncated, {len(content) - self.max_result_size} chars omitted]"

            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=content,
                data=result if isinstance(result, dict) else None,
                is_error=is_handler_error,
                error=result.get("error") if is_handler_error else None,
            )

        except TimeoutError:
            duration = time.time() - start_time
            logger.warning(f"Tool '{tool_call.name}' timed out after {duration:.2f}s")
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Error: Tool execution timed out after {self.default_timeout}s",
                error="timeout",
                is_error=True,
            )

        except asyncio.CancelledError:
            duration = time.time() - start_time
            logger.warning(f"Tool '{tool_call.name}' cancelled after {duration:.2f}s")
            raise

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Tool '{tool_call.name}' failed after {duration:.2f}s: {e}")
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Error: Tool execution failed - {str(e)}",
                error=str(e),
                is_error=True,
            )

    async def execute_multiple(self, tool_calls):
        tasks = [asyncio.create_task(self.execute(tc)) for tc in tool_calls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                tc = tool_calls[i]
                final_results.append(ToolResult(
                    tool_call_id=tc.id,
                    name=tc.name,
                    content=f"Error: {str(result)}",
                    error=str(result),
                    is_error=True,
                ))
            else:
                final_results.append(result)

        return final_results

    def _validate_arguments(self, tool_def, arguments):
        from .schemas import validate_tool_arguments
        return validate_tool_arguments(tool_def, arguments)

    async def _execute_with_timeout(self, handler, arguments, timeout=None):
        timeout = timeout or self.default_timeout

        if asyncio.iscoroutinefunction(handler):
            return await asyncio.wait_for(handler(**arguments), timeout=timeout)
        else:
            loop = asyncio.get_event_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: handler(**arguments)),
                timeout=timeout
            )

    def cancel_all(self):
        for task in self._active_tasks.values():
            task.cancel()
        self._active_tasks.clear()


executor = ToolExecutor()
