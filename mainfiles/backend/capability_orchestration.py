"""
Capability Orchestration — Phase 7

Determines which tools/capabilities should be offered to the model based on
the user's request and Phase 6 response intelligence guidance.

Pure local heuristics - NO second LLM call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.tools.schemas import ToolDefinition


@dataclass
class CapabilityDecision:
    """Result of capability decision process."""

    # High-level capability classification
    capability_required: str = "none"  # "none", "tool", "research", "file", "artifact"

    # Tool requirement level
    tool_requirement: str = "none"  # "none", "possible", "required"

    # Action mode for the model
    action_mode: str = "answer"  # "answer", "investigate", "execute", "transform", "clarify"

    # Confidence in this decision
    confidence: str = "low"  # "low", "medium", "high"

    # Filtered tool list to pass to provider (subset of available tools)
    filtered_tools: list[ToolDefinition] = field(default_factory=list)

    # Explanation for debugging/logging
    reasoning: str = ""

    # Whether Phase 6 signals strongly indicate tool use
    phase6_tool_signals: bool = False


# --- Intent signal keywords for capability detection ---

# Strong indicators that a specific tool is explicitly requested
EXPLICIT_TOOL_KEYWORDS = {
    "list_files": [
        "list files", "list the files", "show files", "show me files",
        "what files", "files in", "directory contents", "list directory",
    ],
    "read_file": [
        "read file", "read the file", "show file", "show me the file",
        "cat file", "view file", "open file",
        "read ", "view ", "open ", "cat ",  # Matches "Read backend/api.py", "View file.py", etc.
    ],
    "web_search": [
        "search web", "search the web", "web search", "google", "look up",
        "find information", "search for", "lookup",
    ],
    "execute_code": [
        "execute code", "run code", "run this code", "execute this code", "execute this",
        "run python", "execute python",
    ],
}

# Direct answer triggers - questions that typically have direct answers
DIRECT_ANSWER_TRIGGERS = [
    "what is", "what are", "who is", "who was", "where is", "where was",
    "when is", "when was", "why is", "why are", "how is", "how are",
    "capital of", "population of", "definition of", "meaning of",
]

# Coding-related terms that DON'T necessarily need tools
CODING_NO_TOOL = [
    "explain", "what is", "how does", "why", "concept", "understand",
    "learn", "tutorial", "guide", "example", "definition", "meaning",
]

# Triggers that suggest file system access might be needed
FILESYSTEM_TRIGGERS = [
    "file", "files", "directory", "folder", "project", "codebase",
    "repository", "repo", "source", "path",
]

# Triggers that suggest web search might be needed
WEB_TRIGGERS = [
    "news", "latest", "current", "today", "recent", "up to date",
    "search", "find", "lookup", "who won", "what happened",
]


def _mode_str(mode: Any) -> str:
    """Extract string value from QueryMode enum or return string as-is."""
    if mode is None:
        return ""
    # QueryMode is a StrEnum, so str(mode) gives the value like "coding"
    # But if passed as enum, we want the value
    if hasattr(mode, 'value'):
        return str(mode.value)
    s = str(mode)
    # If it's the enum representation like "QueryMode.CODING", extract the value
    if '.' in s:
        s = s.split('.')[-1]
    return s.lower()


def detect_capability_signals(
    user_message: str,
    guidance_intent: Any,
    guidance_mode: Any,
) -> dict[str, bool]:
    """
    Detect which capability signals are present in the request.

    Returns a dict with signals for each capability type.
    """
    msg_lower = user_message.lower().strip()

    signals = {
        "explicit_list_files": False,
        "explicit_read_file": False,
        "explicit_web_search": False,
        "explicit_execute_code": False,
        "filesystem_context": False,
        "web_context": False,
        "code_execution_context": False,
        "pure_explanation": False,
        "direct_answer": False,
    }

    # Check explicit tool requests (high confidence)
    for tool, keywords in EXPLICIT_TOOL_KEYWORDS.items():
        for kw in keywords:
            if kw in msg_lower:
                signals[f"explicit_{tool}"] = True
                break

    # Check filesystem context
    if any(t in msg_lower for t in FILESYSTEM_TRIGGERS):
        signals["filesystem_context"] = True

    # Check web context
    if any(t in msg_lower for t in WEB_TRIGGERS):
        signals["web_context"] = True

    # Check code execution context
    if "execute" in msg_lower or "run" in msg_lower:
        # But only if it's about running code, not just "run through this"
        if any(t in msg_lower for t in ["code", "script", "python", "function"]):
            signals["code_execution_context"] = True

    # Check for pure explanation/training (no tool needed)
    mode_str = _mode_str(guidance_mode)
    if mode_str in ("instructional", "factual", "conversational"):
        if any(t in msg_lower for t in CODING_NO_TOOL):
            signals["pure_explanation"] = True

    # Check for direct answer questions (factual questions with known answers)
    if mode_str in ("factual", "conversational"):
        if any(t in msg_lower for t in DIRECT_ANSWER_TRIGGERS):
            signals["direct_answer"] = True

    return signals


def capability_decide(
    user_message: str,
    enabled_tools: list[ToolDefinition],
    guidance: Any,
) -> CapabilityDecision:
    """
    Main entry point: decide which capabilities/tools to offer the model.

    This is the ONLY function that should be called from providers/__init__.py
    or api.py for capability orchestration.

    Args:
        user_message: The latest user message content
        enabled_tools: All currently enabled ToolDefinition objects
        guidance: ResponseGuidance object from Phase 6 (contains mode, intent, profile)

    Returns:
        CapabilityDecision with filtered tool list and metadata
    """
    msg_lower = user_message.lower().strip()

    # Get mode and intent from guidance (with fallbacks)
    mode = getattr(guidance, "mode", None)
    intent = getattr(guidance, "intent", None)
    mode_str = _mode_str(mode)

    # Detect capability signals
    signals = detect_capability_signals(msg_lower, intent, mode)

    # Build tool lookup
    tools_by_name = {t.name: t for t in enabled_tools}

    # Default decision: conservative - all enabled tools available
    decision = CapabilityDecision(
        capability_required="none",
        tool_requirement="none",
        action_mode="answer",
        confidence="low",
        filtered_tools=enabled_tools.copy(),  # Conservative: all tools available
        reasoning="Default: all enabled tools available",
    )

    # SPECIAL CASE: Analysis mode with filesystem context -> conservative (all tools)
    # This handles "Investigate why my project is broken" - ambiguous, investigative
    if mode_str == "analysis" and signals["filesystem_context"] and tools_by_name:
        decision.capability_required = "tool"
        decision.tool_requirement = "possible"
        decision.action_mode = "investigate"
        decision.confidence = "low"
        decision.filtered_tools = enabled_tools
        decision.reasoning = "Analysis mode + filesystem context - all tools available for model decision"
        decision.phase6_tool_signals = False
        return decision

    # Check for direct answer questions FIRST - these don't need tools
    if signals["direct_answer"]:
        decision.capability_required = "none"
        decision.tool_requirement = "none"
        decision.action_mode = "answer"
        decision.confidence = "high"
        decision.filtered_tools = []
        decision.reasoning = "Direct answer question detected - no tool needed"
        decision.phase6_tool_signals = False
        return decision

    # HIGH CONFIDENCE: Explicit tool request -> filter to that tool
    explicit_tools = []
    explicit_tool_names = []
    if signals["explicit_list_files"] and "list_files" in tools_by_name:
        explicit_tools.append(tools_by_name["list_files"])
        explicit_tool_names.append("list_files")
    if signals["explicit_read_file"] and "read_file" in tools_by_name:
        explicit_tools.append(tools_by_name["read_file"])
        explicit_tool_names.append("read_file")
    if signals["explicit_web_search"] and "web_search" in tools_by_name:
        explicit_tools.append(tools_by_name["web_search"])
        explicit_tool_names.append("web_search")
    if signals["explicit_execute_code"] and "execute_code" in tools_by_name:
        explicit_tools.append(tools_by_name["execute_code"])
        explicit_tool_names.append("execute_code")

    if explicit_tools:
        # Determine capability type based on which tool was explicitly requested
        if "web_search" in explicit_tool_names:
            decision.capability_required = "research"
        else:
            # list_files, read_file, execute_code all use "tool"
            decision.capability_required = "tool"

        decision.tool_requirement = "required"
        decision.action_mode = "execute"
        decision.confidence = "high"
        decision.filtered_tools = explicit_tools
        decision.reasoning = f"Explicit tool request detected: {explicit_tool_names}"
        decision.phase6_tool_signals = True
        return decision

    # MEDIUM CONFIDENCE: Strong context signals + Phase 6 intent
    # File system access
    if signals["filesystem_context"] and ("list_files" in tools_by_name or "read_file" in tools_by_name):
        # Only if Phase 6 suggests action/instructional mode
        if mode_str in ("instructional", "coding", "analysis"):
            file_tools = []
            if "list_files" in tools_by_name:
                file_tools.append(tools_by_name["list_files"])
            if "read_file" in tools_by_name:
                file_tools.append(tools_by_name["read_file"])
            if file_tools:
                decision.capability_required = "file"
                decision.tool_requirement = "possible"
                decision.action_mode = "investigate"
                decision.confidence = "medium"
                decision.filtered_tools = file_tools
                decision.reasoning = "Filesystem context + instructional/coding/analysis mode"
                decision.phase6_tool_signals = True
                return decision

    # Web search
    if signals["web_context"] and "web_search" in tools_by_name:
        if mode_str in ("factual", "instructional", "analysis"):
            decision.capability_required = "research"
            decision.tool_requirement = "possible"
            decision.action_mode = "investigate"
            decision.confidence = "medium"
            decision.filtered_tools = [tools_by_name["web_search"]]
            decision.reasoning = "Web search context + factual/instructional/analysis mode"
            decision.phase6_tool_signals = True
            return decision

    # Code execution - contextual (not explicit)
    if signals["code_execution_context"] and "execute_code" in tools_by_name:
        if mode_str == "coding":
            decision.capability_required = "tool"
            decision.tool_requirement = "possible"  # Contextual, not explicit
            decision.action_mode = "execute"
            decision.confidence = "medium"
            decision.filtered_tools = [tools_by_name["execute_code"]]
            decision.reasoning = "Code execution context + coding mode"
            decision.phase6_tool_signals = True
            return decision

    # LOW CONFIDENCE / DEFAULT: No specific tool signals
    # For pure explanation/training, no tools needed
    if signals["pure_explanation"]:
        decision.capability_required = "none"
        decision.tool_requirement = "none"
        decision.action_mode = "answer"
        decision.confidence = "high"
        decision.filtered_tools = []
        decision.reasoning = "Pure explanation detected - no tool needed"
        decision.phase6_tool_signals = False
        return decision

    # Default conservative: return all enabled tools (model decides)
    if mode_str == "coding" and tools_by_name:
        # Coding mode might need various tools - keep all available
        decision.capability_required = "tool"
        decision.tool_requirement = "possible"
        decision.action_mode = "answer"
        decision.confidence = "low"
        decision.filtered_tools = enabled_tools
        decision.reasoning = "Coding mode - all tools available for model decision"
        decision.phase6_tool_signals = False
    else:
        # Other modes: conservative - all tools but low confidence
        decision.reasoning = "No strong signals - all tools available for model decision"

    return decision