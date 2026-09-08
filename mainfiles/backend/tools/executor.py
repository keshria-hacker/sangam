"""Tool executor for running tool calls."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.tools.registry import ToolRegistry, registry
from backend.tools.schemas import ToolCall, ToolResult

logger = logging.getLogger(__name__)


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
    ):
        self.registry = tool_registry or registry
        self.default_timeout = default_timeout
        self.max_result_size = max_result_size
        self._active_tasks = {}

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        start_time = time.time()
        tool_def = self.registry.get(tool_call.name)

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
            result = await self._execute_with_timeout(tool_def.handler, tool_call.arguments)
            duration = time.time() - start_time
            logger.info(f"Tool '{tool_call.name}' executed in {duration:.2f}s")

            # Check if handler returned an error dict
            is_handler_error = isinstance(result, dict) and "error" in result
            content = str(result)
            if len(content) > self.max_result_size:
                content = content[:self.max_result_size] + f"\n... [truncated, {len(result) - self.max_result_size} chars omitted]"

            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=content,
                data=result if isinstance(result, dict) else None,
                is_error=is_handler_error,
                error=result.get("error") if is_handler_error else None,
            )

        except asyncio.TimeoutError:
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
        from backend.tools.schemas import validate_tool_arguments
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
