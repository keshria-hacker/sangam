"""
skills/executor.py — hardened skill execution with timeouts, retries,
and structured error handling. Replaces the inline _call() in router.py.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from backend import llm
from backend.database import AsyncSessionLocal
from pydantic import BaseModel, ValidationError, create_model
from backend.skills.registry import SkillDefinition, get_registry
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Default timeout for a single skill execution (seconds)
DEFAULT_SKILL_TIMEOUT = 60.0

# Maximum tokens for skill completion (kept small for speed on local models)
DEFAULT_MAX_TOKENS = 1500

# Default temperature for skill execution (lower = more deterministic)
DEFAULT_TEMPERATURE = 0.3

# Retry configuration for transient LLM errors
RETRY_ATTEMPTS = 3
RETRY_MIN_WAIT = 1.0
RETRY_MAX_WAIT = 10.0

# Exceptions that should trigger a retry (transient errors)
RETRYABLE_EXCEPTIONS = (
    asyncio.TimeoutError,
    ConnectionError,
    TimeoutError,
)


@dataclass
class ExecutionResult:
    """Structured result of a skill execution."""
    skill_id: str
    skill_name: str
    result: str | None = None
    error: str | None = None
    duration_ms: int = 0
    retries: int = 0
    model_used: str | None = None


_TYPE_MAP = {
    "string": str,
    "str": str,
    "integer": int,
    "int": int,
    "number": float,
    "float": float,
    "boolean": bool,
    "bool": bool,
    "array": list,
    "list": list,
    "object": dict,
    "dict": dict,
}


def _build_validation_model(skill: SkillDefinition) -> type[BaseModel]:
    """
    Build a Pydantic model for validating skill parameters at runtime.

    The model is created dynamically based on the skill's parameter definitions,
    providing type coercion and validation without requiring predefined models.
    """
    fields: dict[str, tuple[type[Any], Any]] = {}

    for param in skill.parameters:
        param_type = _TYPE_MAP.get(param.type.lower())
        if param_type is None:
            # Unknown type - default to Any (str) but log a warning
            logger.warning(f"Skill '{skill.id}' parameter '{param.name}' has unknown type '{param.type}', defaulting to str")
            param_type = str

        if param.required:
            fields[param.name] = (param_type, ...)
        else:
            default_value = param.default if param.default is not None else None
            fields[param.name] = (param_type | None, default_value)

    model_name = f"{skill.id.capitalize()}Validation"
    # Forbid extra fields at model creation time to prevent tool argument injection
    model = create_model(
        model_name,
        __config__={"extra": "forbid"},
        **fields,
    )
    return model


class SkillExecutor:
    """
    Hardened skill executor with:
    - Per-skill timeout (configurable, with global default)
    - Automatic retries with exponential backoff for transient errors
    - Structured logging and timing
    - Clear error categorization (timeout, model error, validation error, etc.)
    - Pydantic parameter validation against skill definitions
    """

    def __init__(
        self,
        default_timeout: float = DEFAULT_SKILL_TIMEOUT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ):
        self.default_timeout = default_timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.registry = get_registry()
        self._validation_cache: dict[str, type[BaseModel]] = {}

    def _get_validation_model(self, skill: SkillDefinition) -> type[BaseModel]:
        """Get or create validation model for a skill (cached)."""
        if skill.id not in self._validation_cache:
            self._validation_cache[skill.id] = _build_validation_model(skill)
        return self._validation_cache[skill.id]

    def _validate_params(self, skill: SkillDefinition, params: dict[str, Any]) -> dict[str, Any]:
        """
        Validate and coerce parameters against skill definition.

        Returns the validated/coerced parameters dict.
        Raises ValueError with descriptive message on validation failure.
        """
        validation_model = self._get_validation_model(skill)

        try:
            validated = validation_model(**params)
            return validated.model_dump()
        except ValidationError as exc:
            errors = []
            for error in exc.errors():
                field = " -> ".join(str(loc) for loc in error["loc"])
                msg = error["msg"]
                errors.append(f"{field}: {msg}")
            raise ValueError(f"Parameter validation failed: {'; '.join(errors)}")

    async def execute(
        self,
        skill_id: str,
        params: dict[str, Any],
        timeout: float | None = None,
    ) -> ExecutionResult:
        """
        Execute a single skill with timeout and retry protection.

        Args:
            skill_id: The skill ID to execute
            params: Parameter dictionary for the skill
            timeout: Override timeout in seconds (None = use default)

        Returns:
            ExecutionResult with result/error/timing metadata
        """
        skill = self.registry.get(skill_id)
        if skill is None:
            return ExecutionResult(
                skill_id=skill_id,
                skill_name=skill_id,
                error=f"Skill not found: {skill_id}",
                duration_ms=0,
            )

        start_time = time.monotonic()
        effective_timeout = timeout if timeout is not None else self.default_timeout

        # Validate parameters against skill definition (prevents tool argument injection)
        try:
            validated_params = self._validate_params(skill, params)
        except ValueError as exc:
            return ExecutionResult(
                skill_id=skill_id,
                skill_name=skill.name,
                error=f"Parameter validation failed: {exc}",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        # Build the prompt, resolving dependencies first
        try:
            prompt = await self._build_prompt_with_deps(skill_id, validated_params)
        except ValueError as exc:
            return ExecutionResult(
                skill_id=skill_id,
                skill_name=skill.name,
                error=f"Parameter validation failed: {exc}",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        # Execute with timeout and retry
        try:
            result, model_id = await asyncio.wait_for(
                self._execute_with_retry(prompt, skill),
                timeout=effective_timeout,
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return ExecutionResult(
                skill_id=skill_id,
                skill_name=skill.name,
                result=result,
                duration_ms=duration_ms,
                model_used=model_id,
            )
        except TimeoutError:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning(f"Skill '{skill.id}' timed out after {effective_timeout}s")
            return ExecutionResult(
                skill_id=skill_id,
                skill_name=skill.name,
                error=f"Execution timed out after {effective_timeout:.0f}s",
                duration_ms=duration_ms,
            )
        except Exception as exc:  # noqa: BLE001 — surfaced as structured error
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = self._categorize_error(exc)
            logger.error(f"Skill '{skill.id}' failed: {error_msg}", exc_info=True)
            return ExecutionResult(
                skill_id=skill_id,
                skill_name=skill.name,
                error=error_msg,
                duration_ms=duration_ms,
            )

    async def _build_prompt_with_deps(
        self, skill_id: str, params: dict[str, Any]
    ) -> str:
        """Execute dependencies first, then build prompt with their results."""
        # Resolve dependency graph
        dep_skills = self.registry.resolve(skill_id)

        # Execute dependencies and collect their results
        context: dict[str, str] = {}
        for dep in dep_skills:
            if dep.id == skill_id:
                continue
            dep_params = params.get(dep.id, {})
            dep_result = await self.execute(dep.id, dep_params)
            if dep_result.result:
                context[f"{dep.id}_result"] = dep_result.result
            elif dep_result.error:
                context[f"{dep.id}_error"] = dep_result.error

        # Merge dependency results into params and build final prompt
        merged_params = {**params, **context}
        return self.registry.build_prompt(skill_id, **merged_params)

    async def _execute_with_retry(self, prompt: str, skill: SkillDefinition) -> tuple[str, str]:
        """Execute the LLM call with retry logic for transient failures.

        Returns:
            tuple of (result_content, model_id_used)
        """
        async with AsyncSessionLocal() as db:
            model_id = await llm.default_model_id(db)
            if not model_id:
                raise ValueError(
                    "No model available. Link a provider key in Settings or "
                    "start Ollama with a pulled model before running a skill."
                )

            messages = [{"role": "system", "content": prompt}]

            # Use tenacity for automatic retries on transient errors
            async for attempt in AsyncRetrying(
                reraise=True,
                stop=stop_after_attempt(RETRY_ATTEMPTS),
                wait=wait_exponential(
                    multiplier=1, min=RETRY_MIN_WAIT, max=RETRY_MAX_WAIT
                ),
                retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
                before_sleep=lambda retry_state: logger.warning(
                    f"Skill '{skill.id}' attempt {retry_state.attempt_number} "
                    f"failed: {retry_state.outcome.exception()}; "
                    f"retrying in {retry_state.next_action.sleep:.1f}s"
                ),
            ):
                with attempt:
                    content = ""
                    async for token in llm.stream_completion(
                        model_id=model_id,
                        messages=messages,
                        db=db,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    ):
                        content += token

                    if not content:
                        raise ValueError("Model returned empty response")

                    return content, model_id

    def _categorize_error(self, exc: Exception) -> str:
        """Convert exception to user-friendly error message with category."""
        exc_type = type(exc).__name__
        exc_msg = str(exc)

        if isinstance(exc, asyncio.TimeoutError):
            return "Timeout: Skill execution exceeded time limit"
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return f"Network error: {exc_msg}"
        if isinstance(exc, ValueError):
            return f"Validation error: {exc_msg}"
        if "rate limit" in exc_msg.lower() or "429" in exc_msg:
            return f"Rate limited: {exc_msg}"
        if "unauthorized" in exc_msg.lower() or "401" in exc_msg:
            return "Authentication failed: Check API key for provider"
        if "not found" in exc_msg.lower() or "404" in exc_msg:
            return f"Model not found: {exc_msg}"
        if "context length" in exc_msg.lower() or "token limit" in exc_msg.lower():
            return "Context too large: Try a model with larger context window"

        return f"{exc_type}: {exc_msg}"

    async def execute_chain(
        self, chain: list[dict[str, Any]], timeout_per_skill: float | None = None
    ) -> list[ExecutionResult]:
        """
        Execute a chain of skills sequentially, passing results forward.

        Each step receives the accumulated results from previous steps.
        """
        results: list[ExecutionResult] = []
        context: dict[str, str] = {}

        for i, step in enumerate(chain):
            skill_id = step.get("skill")
            step_params = {**step.get("params", {}), **context}

            if not skill_id:
                results.append(ExecutionResult(
                    skill_id=f"step_{i}",
                    skill_name=f"step_{i}",
                    error="Missing 'skill' in chain step",
                ))
                continue

            result = await self.execute(skill_id, step_params, timeout_per_skill)
            results.append(result)

            if result.result:
                context[f"{skill_id}_result"] = result.result
            if result.error:
                context[f"{skill_id}_error"] = result.error

        return results


_executor: SkillExecutor | None = None


def get_executor() -> SkillExecutor:
    """Get or create the global skill executor."""
    global _executor
    if _executor is None:
        _executor = SkillExecutor()
    return _executor