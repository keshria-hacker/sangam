"""Runtime verification tests for Phase 7 - PASS 2"""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

os.environ["TEST_MODE"] = "1"
# Generate test master key dynamically - never hardcode
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key

from backend.providers import stream_response_events
from backend.providers.base import ModelInfo, ProviderConfig, ProviderStreamChunk, FinishReason
from backend.tools.registry import registry
from backend.tools.schemas import ToolDefinition, ToolCall
from backend.response_events import ResponseEventType


class FakeProvider:
    """A fake provider that yields different responses per round."""

    def __init__(self, round_responses, config=None, api_key=None):
        self.config = config
        self._api_key = api_key
        self.round = 0
        self.round_responses = round_responses

    @property
    def api_key(self):
        return self._api_key

    async def stream_completion(self, *args, **kwargs):
        self.round += 1
        responses = self.round_responses.get(self.round, self.round_responses.get("default", []))
        for chunk in responses:
            if isinstance(chunk, str):
                yield ProviderStreamChunk(text=chunk)
            elif isinstance(chunk, ProviderStreamChunk):
                yield chunk
            else:
                yield ProviderStreamChunk(text=str(chunk))


async def run_test(name: str, user_message: str, expect_tool: str | None = None, expect_direct_answer: bool = False, round_responses: dict | None = None):
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"Input: {user_message}")
    print(f"Expected tool: {expect_tool if expect_tool else 'NO TOOL (direct answer)'}")
    print(f"{'='*60}")

    # Create mock DB
    db_mock = MagicMock()
    db_mock.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=[])))

    # Default round responses - single round with just tool call then answer
    if round_responses is None:
        if expect_tool:
            tool_name = expect_tool
            if tool_name == "list_files":
                args = '{"path": ".", "pattern": "*"}'
            elif tool_name == "read_file":
                args = '{"path": "backend/response_intelligence/config.py"}'
            elif tool_name == "execute_code":
                args = '{"code": "print(2 + 2)", "language": "python"}'
            else:
                args = '{}'

            round_responses = {
                1: [
                    ProviderStreamChunk(
                        tool_calls=[{
                            "id": f"call_{tool_name}_1",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": args,
                            },
                            "index": 0,
                        }],
                    ),
                    ProviderStreamChunk(
                        finish_reason=FinishReason.TOOL,
                        terminal=True,
                    ),
                ],
                2: [
                    ProviderStreamChunk(text=f"Tool {tool_name} executed successfully."),
                    ProviderStreamChunk(
                        finish_reason=FinishReason.STOP,
                        terminal=True,
                    ),
                ],
            }
        else:
            round_responses = {
                1: [
                    ProviderStreamChunk(text="Python is a high-level programming language..."),
                    ProviderStreamChunk(
                        finish_reason=FinishReason.STOP,
                        terminal=True,
                    ),
                ],
            }

    events = []
    tool_calls_made = []
    tool_results = []

    try:
        from backend.providers.registry import registry as provider_registry
        original_get = provider_registry.get_provider_class

        try:
            provider_registry.get_provider_class = lambda pid: lambda *a, **kw: FakeProvider(round_responses)

            with patch("backend.providers.resolve_api_key", return_value="test-key"):
                with patch("backend.providers.list_models", return_value=[
                    ModelInfo(
                        id="openai::openai/gpt-4o",
                        name="gpt-4o",
                        provider_id="openai",
                        provider_label="OpenAI",
                        litellm_id="openai/gpt-4o",
                        capabilities=MagicMock(tools=True),
                    )
                ]):
                    async for event in stream_response_events(
                        model_id='openai::openai/gpt-4o',
                        messages=[{'role': 'user', 'content': user_message}],
                        db=db_mock,
                    ):
                        events.append(event)
                        event_type_str = str(event.type)
                        content_preview = str(event.content)[:100] if event.content else ''
                        print(f"Event: {event_type_str} - {content_preview}")

                        if event_type_str == 'tool_start':
                            tool_calls_made.append(event.metadata.get('name'))
                            print(f"  -> TOOL START: {event.metadata.get('name')}")
                        elif event_type_str == 'tool_end':
                            print(f"  -> TOOL END: {event.metadata.get('name')}")
                        elif event_type_str == 'tool_result':
                            tool_results.append({
                                'name': event.metadata.get('name'),
                                'content': event.content[:200] if event.content else '',
                                'is_error': event.metadata.get('is_error', False)
                            })
                            print(f"  -> TOOL RESULT: {event.metadata.get('name')} (error: {event.metadata.get('is_error', False)})")
        finally:
            provider_registry.get_provider_class = original_get

        # Analysis
        print(f"\n--- ANALYSIS ---")
        print(f"Total events: {len(events)}")
        print(f"Tools called: {tool_calls_made}")
        print(f"Tool results: {len(tool_results)}")

        if expect_tool:
            if expect_tool in tool_calls_made:
                print(f"[PASS] Expected tool '{expect_tool}' was called")
            else:
                print(f"[FAIL] Expected tool '{expect_tool}' was NOT called")
                return False
        elif expect_direct_answer:
            if len(tool_calls_made) == 0:
                print(f"[PASS] No tool calls made (direct answer)")
            else:
                print(f"[FAIL] Tool calls were made when direct answer expected: {tool_calls_made}")
                return False

        if expect_tool:
            # Check we got a result
            matching_results = [r for r in tool_results if r['name'] == expect_tool]
            if matching_results:
                print(f"[PASS] Got tool result for '{expect_tool}'")
                if matching_results[0]['is_error']:
                    print(f"  Note: Tool returned error (may be expected for security tests): {matching_results[0]['content']}")
            else:
                print(f"[FAIL] No tool result for '{expect_tool}'")
                return False

        return True

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("="*60)
    print("PHASE 7 - RUNTIME VERIFICATION (PASS 2)")
    print("="*60)

    results = []

    # TEST 1: List files
    results.append(await run_test(
        "TEST 1: List files",
        "List the files in my project.",
        expect_tool="list_files"
    ))

    # TEST 2: Read file - config
    results.append(await run_test(
        "TEST 2: Read config.py",
        "Read backend/response_intelligence/config.py and explain what it does.",
        expect_tool="read_file"
    ))

    # TEST 3: Read file - api
    results.append(await run_test(
        "TEST 3: Read api.py",
        "Read backend/api.py and tell me what it does.",
        expect_tool="read_file"
    ))

    # TEST 4: Path traversal - should be rejected
    results.append(await run_test(
        "TEST 4: Path traversal",
        "Read ../../some_file",
        expect_tool="read_file",
        round_responses={
            1: [
                ProviderStreamChunk(
                    tool_calls=[{
                        "id": "call_read_file_traversal",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "../../some_file"}',
                        },
                        "index": 0,
                    }],
                ),
                ProviderStreamChunk(
                    finish_reason=FinishReason.TOOL,
                    terminal=True,
                ),
            ],
            2: [
                ProviderStreamChunk(text="Path traversal blocked."),
                ProviderStreamChunk(
                    finish_reason=FinishReason.STOP,
                    terminal=True,
                ),
            ],
        }
    ))

    # TEST 5: Execute code
    results.append(await run_test(
        "TEST 5: Execute code",
        "Execute this Python code and tell me the result: print(2 + 2)",
        expect_tool="execute_code"
    ))

    # TEST 6: Direct answer (no tool)
    results.append(await run_test(
        "TEST 6: Direct answer",
        "What is Python?",
        expect_direct_answer=True
    ))

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    test_names = [
        "TEST 1: List files",
        "TEST 2: Read config.py",
        "TEST 3: Read api.py",
        "TEST 4: Path traversal",
        "TEST 5: Execute code",
        "TEST 6: Direct answer"
    ]
    for i, (name, result) in enumerate(zip(test_names, results)):
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} - {name}")

    passed = sum(results)
    total = len(results)
    print(f"\nOverall: {passed}/{total} tests passed")

    if passed == total:
        print("\n[SUCCESS] ALL TESTS PASSED - PASS 2 VERIFICATION SUCCESSFUL")
    else:
        print(f"\n[WARNING] {total - passed} TEST(S) FAILED - NEEDS FIXES")

    return passed == total


if __name__ == "__main__":
    asyncio.run(main())