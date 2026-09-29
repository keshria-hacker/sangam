"""
Tests for skills/executor.py branch coverage - targeting uncovered lines:
- 89-90: Unknown param type defaults to str with warning
- 199-200: _build_prompt_with_deps validation error handling
- 253-258: Dependency execution error handling (context error storage)
- 269: No model available error
- 302: Empty response from model raises ValueError
"""
import os
import sys
import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mainfiles"))

# Enable test mode
os.environ["TEST_MODE"] = "1"
import base64
from cryptography.fernet import Fernet

# Generate test master key dynamically - never hardcode
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key


# Import the required classes
from backend.skills.registry import SkillCategory, InvocationType, SkillDefinition, SkillParameter, get_registry
from backend.skills.executor import SkillExecutor, ExecutionResult, _build_validation_model
import backend.skills.executor as skills_executor_module


class BuildValidationModelTests(unittest.TestCase):
    """Tests for _build_validation_model function (lines 89-90)."""

    def setUp(self):
        # Reset global executor singleton
        skills_executor_module._executor = None

    def test_unknown_param_type_defaults_to_str_with_warning(self):
        """Unknown param type logs warning and defaults to str (lines 89-90)."""
        import logging
        from backend.skills.executor import _build_validation_model

        # Capture log output
        with self.assertLogs(level=logging.WARNING) as cm:
            skill = SkillDefinition(
                id="test_skill",
                name="Test Skill",
                category=SkillCategory.MISC,
                invocation=InvocationType.BOTH,
                description="Test",
                parameters=[
                    SkillParameter(name="param1", type="unknown_type", required=True, default=None, description="Test")
                ],
                prompt_template="Test {{param1}}"
            )
            model = _build_validation_model(skill)

        # Verify warning was logged
        self.assertIn("unknown type", cm.output[0])
        self.assertIn("defaulting to str", cm.output[0])

        # Verify model works with string
        instance = model(param1="test")
        self.assertEqual(instance.param1, "test")


class SkillExecutorValidationTests(unittest.TestCase):
    """Tests for parameter validation in SkillExecutor."""

    def setUp(self):
        """Set up executor with mocked registry."""
        # Get the existing registry and clear it
        from backend.skills.registry import get_registry
        from backend.skills.executor import SkillExecutor

        self.registry = get_registry()
        self.registry.skills = {}
        self.registry._dependencies = {}

        # Create a test skill
        self.test_skill = SkillDefinition(
            id="test_skill",
            name="Test Skill",
            category=SkillCategory.MISC,
            invocation=InvocationType.BOTH,
            description="Test skill",
            parameters=[
                SkillParameter(name="param1", type="string", required=True, default=None, description="Required param"),
                SkillParameter(name="param2", type="integer", required=False, default=42, description="Optional param"),
            ],
            prompt_template="Test {{param1}} {{param2}}"
        )
        self.registry.skills[self.test_skill.id] = self.test_skill

        self.executor = SkillExecutor()

    def test_validate_params_valid(self):
        """Valid parameters pass validation."""
        result = self.executor._validate_params(self.test_skill, {"param1": "hello", "param2": 10})
        self.assertEqual(result["param1"], "hello")
        self.assertEqual(result["param2"], 10)

    def test_validate_params_missing_required(self):
        """Missing required parameter raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.executor._validate_params(self.test_skill, {"param2": 10})
        self.assertIn("Parameter validation failed", str(ctx.exception))
        self.assertIn("param1", str(ctx.exception))

    def test_validate_params_type_coercion(self):
        """Type coercion works for valid types."""
        result = self.executor._validate_params(self.test_skill, {"param1": "hello", "param2": "42"})
        self.assertEqual(result["param2"], 42)  # String "42" coerced to int

    def test_validate_params_invalid_type(self):
        """Invalid type raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.executor._validate_params(self.test_skill, {"param1": "hello", "param2": "not_a_number"})
        self.assertIn("Parameter validation failed", str(ctx.exception))

    def test_validate_params_extra_fields_forbidden(self):
        """Extra fields are forbidden (extra='forbid')."""
        with self.assertRaises(ValueError) as ctx:
            self.executor._validate_params(self.test_skill, {"param1": "hello", "extra_field": "bad"})
        self.assertIn("Parameter validation failed", str(ctx.exception))


class SkillExecutorExecuteTests(unittest.TestCase):
    """Tests for SkillExecutor.execute method."""

    def setUp(self):
        from backend.skills.registry import get_registry
        from backend.skills.executor import SkillExecutor

        self.registry = get_registry()
        self.registry.skills = {}
        self.registry._dependencies = {}

        self.test_skill = SkillDefinition(
            id="test_skill",
            name="Test Skill",
            category=SkillCategory.MISC,
            invocation=InvocationType.BOTH,
            description="Test skill",
            parameters=[
                SkillParameter(name="prompt", type="string", required=True, default=None, description="Prompt")
            ],
            prompt_template="Execute: {prompt}"
        )
        self.registry.skills[self.test_skill.id] = self.test_skill

        self.executor = SkillExecutor()

    def test_execute_skill_not_found(self):
        """Unknown skill returns error result (lines 173-180)."""

        async def test():
            result = await self.executor.execute("nonexistent", {})
            self.assertEqual(result.skill_id, "nonexistent")
            self.assertIsNotNone(result.error)
            self.assertIn("Skill not found", result.error)

        asyncio.run(test())

    def test_execute_validation_error_returns_result(self):
        """Validation error returns ExecutionResult with error (lines 188-194)."""

        async def test():
            # Missing required param
            result = await self.executor.execute("test_skill", {})
            self.assertEqual(result.skill_id, "test_skill")
            self.assertIsNotNone(result.error)
            self.assertIn("Parameter validation failed", result.error)

        asyncio.run(test())

    @patch("backend.skills.executor.SkillExecutor._build_prompt_with_deps", return_value="test prompt")
    @patch("backend.skills.executor.SkillExecutor._execute_with_retry")
    def test_execute_timeout_returns_error(self, mock_retry, mock_build_prompt):
        """Timeout returns structured error result (lines 221-229)."""

        mock_retry.side_effect = asyncio.TimeoutError()

        async def test():
            result = await self.executor.execute("test_skill", {"prompt": "test"}, timeout=1.0)
            self.assertIsNotNone(result.error)
            self.assertIn("timed out", result.error)
            # Duration may be 0 in mocked test, just verify it's present
            self.assertGreaterEqual(result.duration_ms, 0)

        asyncio.run(test())

    @patch("backend.skills.executor.SkillExecutor._build_prompt_with_deps", return_value="test prompt")
    @patch("backend.skills.executor.SkillExecutor._execute_with_retry")
    def test_execute_generic_exception_categorized(self, mock_retry, mock_build_prompt):
        """Generic exception is categorized (lines 230-239)."""

        mock_retry.side_effect = Exception("Some error")

        async def test():
            result = await self.executor.execute("test_skill", {"prompt": "test"})
            self.assertIsNotNone(result.error)

        asyncio.run(test())


class BuildPromptWithDepsTests(unittest.TestCase):
    """Tests for _build_prompt_with_deps (lines 199-200, 253-258)."""

    def setUp(self):
        from backend.skills.registry import get_registry
        from backend.skills.executor import SkillExecutor

        self.registry = get_registry()
        self.registry.skills = {}
        self.registry._dependencies = {}

        # Skill with dependency - add dependency to the skill definition
        self.dep_skill = SkillDefinition(
            id="dep_skill",
            name="Dependency Skill",
            category=SkillCategory.MISC,
            invocation=InvocationType.BOTH,
            description="Dep",
            parameters=[
                SkillParameter(name="input", type="string", required=True, default=None, description="Input")
            ],
            prompt_template="Dep: {input}"
        )
        self.registry.skills[self.dep_skill.id] = self.dep_skill

        self.main_skill = SkillDefinition(
            id="main_skill",
            name="Main Skill",
            category=SkillCategory.MISC,
            invocation=InvocationType.BOTH,
            description="Main",
            parameters=[
                SkillParameter(name="prompt", type="string", required=True, default=None, description="Prompt")
            ],
            prompt_template="Main: {prompt} {dep_skill_result} {dep_skill_error}",
            dependencies=["dep_skill"]  # Add dependency here
        )
        self.registry.skills[self.main_skill.id] = self.main_skill

        self.executor = SkillExecutor()

    @patch("backend.skills.executor.SkillExecutor.execute", new_callable=AsyncMock)
    def test_build_prompt_with_deps_dependency_error_stored(self, mock_execute):
        """Dependency error is stored in context (lines 256-258)."""
        from backend.skills.executor import ExecutionResult

        # Dependency returns error
        mock_execute.return_value = ExecutionResult(
            skill_id="dep_skill",
            skill_name="Dependency Skill",
            error="Dep failed"
        )

        async def test():
            result = await self.executor._build_prompt_with_deps("main_skill", {"prompt": "test", "dep_skill_result": "", "dep_skill_error": ""})
            # Should include error in context
            self.assertIn("Dep failed", result)

        asyncio.run(test())

    @patch("backend.skills.executor.SkillExecutor.execute", new_callable=AsyncMock)
    def test_build_prompt_with_deps_dependency_result_stored(self, mock_execute):
        """Dependency result is stored in context (lines 255-256)."""
        from backend.skills.executor import ExecutionResult

        mock_execute.return_value = ExecutionResult(
            skill_id="dep_skill",
            skill_name="Dependency Skill",
            result="Dep result content"
        )

        async def test():
            result = await self.executor._build_prompt_with_deps("main_skill", {"prompt": "test", "dep_skill_result": "", "dep_skill_error": ""})
            self.assertIn("Dep result content", result)

        asyncio.run(test())

    @patch("backend.skills.executor.SkillExecutor.execute", new_callable=AsyncMock)
    def test_build_prompt_with_deps_validation_error_propagated(self, mock_execute):
        """Validation error from dependency execution is propagated (lines 199-200)."""

        mock_execute.side_effect = ValueError("Validation failed")

        async def test():
            with self.assertRaises(ValueError) as ctx:
                await self.executor._build_prompt_with_deps("main_skill", {"prompt": "test"})
            self.assertIn("Validation failed", str(ctx.exception))

        asyncio.run(test())


class ExecuteWithRetryTests(unittest.TestCase):
    """Tests for _execute_with_retry (lines 269, 302)."""

    def setUp(self):
        from backend.skills.registry import get_registry
        from backend.skills.executor import SkillExecutor

        self.registry = get_registry()
        self.registry.skills = {}
        self.registry._dependencies = {}

        self.test_skill = SkillDefinition(
            id="test_skill",
            name="Test Skill",
            category=SkillCategory.MISC,
            invocation=InvocationType.BOTH,
            description="Test",
            parameters=[
                SkillParameter(name="prompt", type="string", required=True, default=None, description="Prompt")
            ],
            prompt_template="Test: {prompt}"
        )
        self.registry.skills[self.test_skill.id] = self.test_skill

        self.executor = SkillExecutor()

    def test_execute_with_retry_no_model_available(self):
        """No model available raises ValueError (line 269)."""

        async def test():
            with patch("backend.skills.executor.AsyncSessionLocal") as mock_session:
                mock_db = AsyncMock()
                mock_session.return_value.__aenter__.return_value = mock_db

                with patch("backend.skills.executor.llm.default_model_id", new_callable=AsyncMock) as mock_default_model:
                    mock_default_model.return_value = None  # No model

                    with self.assertRaises(ValueError) as ctx:
                        await self.executor._execute_with_retry("test prompt", self.test_skill)
                    self.assertIn("No model available", str(ctx.exception))

        asyncio.run(test())

    @patch("backend.skills.executor.AsyncSessionLocal")
    def test_execute_with_retry_empty_response_raises(self, mock_session_class):
        """Empty response from model raises ValueError (line 302)."""

        async def test():
            mock_db = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_db

            # Mock empty stream - async generator that yields nothing
            async def mock_empty_stream(*args, **kwargs):
                return
                yield  # Make it an async generator

            with patch("backend.skills.executor.llm.default_model_id", new_callable=AsyncMock) as mock_default_model:
                mock_default_model.return_value = "test-model"

                # Create an async generator that yields nothing
                async def empty_agen():
                    return
                    yield

                with patch("backend.skills.executor.llm.stream_completion", return_value=empty_agen()):
                    with self.assertRaises(ValueError) as ctx:
                        await self.executor._execute_with_retry("test prompt", self.test_skill)
                    self.assertIn("Model returned empty response", str(ctx.exception))

        asyncio.run(test())

    @patch("backend.skills.executor.AsyncSessionLocal")
    def test_execute_with_retry_success(self, mock_session_class):
        """Successful execution returns content."""

        async def test():
            mock_db = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_db

            # Create a proper async generator
            async def mock_stream(*args, **kwargs):
                for token in ["Hello", " world"]:
                    yield token

            with patch("backend.skills.executor.llm.default_model_id", new_callable=AsyncMock) as mock_default_model:
                mock_default_model.return_value = "test-model"

                with patch("backend.skills.executor.llm.stream_completion", return_value=mock_stream()):
                    result, model_id = await self.executor._execute_with_retry("test prompt", self.test_skill)
                    self.assertEqual(result, "Hello world")
                    self.assertEqual(model_id, "test-model")

        asyncio.run(test())


class CategorizeErrorTests(unittest.TestCase):
    """Tests for _categorize_error method."""

    def setUp(self):
        from backend.skills.executor import SkillExecutor
        self.executor = SkillExecutor()

    def test_categorize_timeout_error(self):
        """asyncio.TimeoutError categorized as timeout."""
        error = self.executor._categorize_error(asyncio.TimeoutError("Timed out"))
        self.assertIn("Timeout:", error)

    def test_categorize_connection_error(self):
        """ConnectionError categorized as network error."""
        error = self.executor._categorize_error(ConnectionError("Connection refused"))
        self.assertIn("Network error:", error)

    def test_categorize_value_error(self):
        """ValueError categorized as validation error."""
        error = self.executor._categorize_error(ValueError("Invalid input"))
        self.assertIn("Validation error:", error)

    def test_categorize_rate_limit(self):
        """429/rate limit categorized as rate limited."""
        error = self.executor._categorize_error(Exception("Rate limit exceeded: 429"))
        self.assertIn("Rate limited:", error)

    def test_categorize_unauthorized(self):
        """401/unauthorized categorized as auth failed."""
        error = self.executor._categorize_error(Exception("Unauthorized: 401"))
        self.assertIn("Authentication failed:", error)

    def test_categorize_not_found(self):
        """404/not found categorized as model not found."""
        error = self.executor._categorize_error(Exception("Model not found: 404"))
        self.assertIn("Model not found:", error)

    def test_categorize_context_length(self):
        """Context length/token limit categorized."""
        error = self.executor._categorize_error(Exception("Context length exceeded"))
        self.assertIn("Context too large:", error)

    def test_categorize_generic_exception(self):
        """Generic exception returns type and message."""
        error = self.executor._categorize_error(RuntimeError("Something went wrong"))
        self.assertIn("RuntimeError:", error)
        self.assertIn("Something went wrong", error)


class ExecuteChainTests(unittest.TestCase):
    """Tests for execute_chain method."""

    def setUp(self):
        from backend.skills.registry import get_registry
        from backend.skills.executor import SkillExecutor

        self.registry = get_registry()
        self.registry.skills = {}
        self.registry._dependencies = {}

        self.skill1 = SkillDefinition(
            id="skill1",
            name="Skill 1",
            category=SkillCategory.MISC,
            invocation=InvocationType.BOTH,
            description="First",
            parameters=[SkillParameter(name="input", type="string", required=True, default=None, description="In")],
            prompt_template="S1: {input}"
        )
        self.registry.skills[self.skill1.id] = self.skill1

        self.skill2 = SkillDefinition(
            id="skill2",
            name="Skill 2",
            category=SkillCategory.MISC,
            invocation=InvocationType.BOTH,
            description="Second",
            parameters=[SkillParameter(name="input", type="string", required=True, default=None, description="In")],
            prompt_template="S2: {input} {skill1_result}"
        )
        self.registry.skills[self.skill2.id] = self.skill2

        self.executor = SkillExecutor()

    @patch("backend.skills.executor.SkillExecutor.execute")
    def test_execute_chain_missing_skill_field(self, mock_execute):
        """Missing 'skill' in chain step returns error result (lines 344-348)."""

        chain = [
            {"params": {"input": "test"}},  # Missing 'skill' key
        ]

        async def test():
            results = await self.executor.execute_chain(chain)
            self.assertEqual(len(results), 1)
            self.assertIsNotNone(results[0].error)
            self.assertIn("Missing 'skill'", results[0].error)

        asyncio.run(test())

    @patch("backend.skills.executor.SkillExecutor.execute")
    def test_execute_chain_success(self, mock_execute):
        """Successful chain execution passes context forward."""

        call_count = 0

        def mock_execute_impl(skill_id, params, timeout):
            nonlocal call_count
            call_count += 1
            from backend.skills.executor import ExecutionResult
            return ExecutionResult(
                skill_id=skill_id,
                skill_name=skill_id,
                result=f"Result {call_count}"
            )

        mock_execute.side_effect = mock_execute_impl

        chain = [
            {"skill": "skill1", "params": {"input": "test1"}},
            {"skill": "skill2", "params": {"input": "test2"}},
        ]

        async def test():
            results = await self.executor.execute_chain(chain)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].result, "Result 1")
            self.assertEqual(results[1].result, "Result 2")

        asyncio.run(test())


class ExecuteSuccessfulPathTests(unittest.TestCase):
    """Tests for successful execution path (lines 213-214)."""

    def setUp(self):
        from backend.skills.registry import get_registry
        from backend.skills.executor import SkillExecutor

        self.registry = get_registry()
        self.registry.skills = {}
        self.registry._dependencies = {}

        self.test_skill = SkillDefinition(
            id="test_skill",
            name="Test Skill",
            category=SkillCategory.MISC,
            invocation=InvocationType.BOTH,
            description="Test",
            parameters=[
                SkillParameter(name="prompt", type="string", required=True, default=None, description="Prompt")
            ],
            prompt_template="Test: {prompt}"
        )
        # Add model attribute dynamically to test model_used tracking
        self.test_skill.model = "test-model"
        self.registry.skills[self.test_skill.id] = self.test_skill

        self.executor = SkillExecutor()

    @patch("backend.skills.executor.AsyncSessionLocal")
    def test_execute_successful_sets_duration_and_model_used(self, mock_session_class):
        """Successful execution sets duration_ms and model_used (lines 213-214)."""

        async def test():
            mock_db = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_db

            async def mock_stream(*args, **kwargs):
                for token in ["Hello", " world"]:
                    yield token

            with patch("backend.skills.executor.llm.default_model_id", new_callable=AsyncMock) as mock_default_model:
                mock_default_model.return_value = "test-model"

                with patch("backend.skills.executor.llm.stream_completion", return_value=mock_stream()):
                    result = await self.executor.execute("test_skill", {"prompt": "test"})

            self.assertIsNotNone(result.result)
            self.assertEqual(result.result, "Hello world")
            # Duration may be 0 on Windows due to time.monotonic() precision
            self.assertGreaterEqual(result.duration_ms, 0)
            self.assertEqual(result.model_used, "test-model")

        asyncio.run(test())


class ExecuteValueErrorFromDepsTests(unittest.TestCase):
    """Tests for ValueError from _build_prompt_with_deps in execute (lines 199-200)."""

    def setUp(self):
        from backend.skills.registry import get_registry
        from backend.skills.executor import SkillExecutor

        self.registry = get_registry()
        self.registry.skills = {}
        self.registry._dependencies = {}

        self.test_skill = SkillDefinition(
            id="test_skill",
            name="Test Skill",
            category=SkillCategory.MISC,
            invocation=InvocationType.BOTH,
            description="Test",
            parameters=[
                SkillParameter(name="prompt", type="string", required=True, default=None, description="Prompt")
            ],
            prompt_template="Test: {prompt}"
        )
        self.registry.skills[self.test_skill.id] = self.test_skill

        self.executor = SkillExecutor()

    @patch("backend.skills.executor.SkillExecutor._build_prompt_with_deps", new_callable=AsyncMock)
    def test_execute_value_error_from_deps_returns_error_result(self, mock_build_prompt):
        """ValueError from _build_prompt_with_deps returns error result (lines 199-200)."""

        mock_build_prompt.side_effect = ValueError("Dependency validation failed")

        async def test():
            result = await self.executor.execute("test_skill", {"prompt": "test"})
            self.assertIsNotNone(result.error)
            self.assertIn("Dependency validation failed", result.error)
            self.assertGreaterEqual(result.duration_ms, 0)

        asyncio.run(test())


class ExecuteChainErrorContextTests(unittest.TestCase):
    """Tests for execute_chain error context storage (line 357)."""

    def setUp(self):
        from backend.skills.registry import get_registry
        from backend.skills.executor import SkillExecutor

        self.registry = get_registry()
        self.registry.skills = {}
        self.registry._dependencies = {}

        self.skill1 = SkillDefinition(
            id="skill1",
            name="Skill 1",
            category=SkillCategory.MISC,
            invocation=InvocationType.BOTH,
            description="First",
            parameters=[SkillParameter(name="input", type="string", required=True, default=None, description="In")],
            prompt_template="S1: {input}"
        )
        self.registry.skills[self.skill1.id] = self.skill1

        self.executor = SkillExecutor()

    @patch("backend.skills.executor.SkillExecutor.execute")
    def test_execute_chain_error_stored_in_context(self, mock_execute):
        """Error from skill execution is stored in context (line 357)."""
        from backend.skills.executor import ExecutionResult

        mock_execute.return_value = ExecutionResult(
            skill_id="skill1",
            skill_name="Skill 1",
            error="Skill failed"
        )

        chain = [
            {"skill": "skill1", "params": {"input": "test"}},
        ]

        async def test():
            results = await self.executor.execute_chain(chain)
            self.assertEqual(len(results), 1)
            self.assertIsNotNone(results[0].error)
            self.assertEqual(results[0].error, "Skill failed")

        asyncio.run(test())


class GetExecutorTests(unittest.TestCase):
    """Tests for get_executor singleton (lines 368-370)."""

    def test_get_executor_returns_singleton(self):
        """get_executor returns the same instance on multiple calls."""
        from backend.skills.executor import get_executor, SkillExecutor

        # Reset global
        import backend.skills.executor as skills_executor
        skills_executor._executor = None

        executor1 = get_executor()
        executor2 = get_executor()

        self.assertIs(executor1, executor2)
        self.assertIsInstance(executor1, SkillExecutor)

    def test_get_executor_creates_new_if_none(self):
        """get_executor creates new executor if global is None."""
        from backend.skills.executor import get_executor, SkillExecutor

        import backend.skills.executor as skills_executor
        skills_executor._executor = None

        executor = get_executor()
        self.assertIsNotNone(executor)
        self.assertIsInstance(executor, SkillExecutor)


if __name__ == "__main__":
    unittest.main()
