"""response_intelligence/pipeline.py — the unified Auto response pipeline.

This is the single path every chat message takes when the composer is in
Auto mode (spec §4). Stages, in order:

    intake -> intent detection -> context assembly -> complexity scoring ->
    capability selection -> mode selection -> tool/search/file/code/artifact
    routing -> execution hints -> normalized event stream (note) ->
    rendering (note) -> validation -> completion -> post-response actions

RULE-FIRST by design (spec §4.2): cheap deterministic rules decide the
intent. A "small classifier" runs ONLY when two or more rule intents tie
at the top score — and that classifier is itself a deterministic weighted
keyword scorer, not a model call. No provider, no network, and never an
expensive model just to classify. ``classifier_used`` in the decision
records which path ran, so the >=80% rule-coverage claim is measurable
(see tests/test_a2_composer_intelligence.py, which asserts it over the
50-prompt golden set).

Intent classes (spec §4.2): direct_answer, teaching, code_generate,
code_debug, code_refactor, research, file_analysis, artifact_create,
diagram, image, video, voice, agentic_task, clarification, follow_up,
meta.

Composer modes (spec §3.2): auto (default), answer, research, code,
create, agent. The pipeline returns the *resolved* mode: in Auto it is
derived from the intent; with an explicit composer mode the user's
choice wins, except that a video request is always blocked (video is
SKIPPED this round upstream) and a follow-up always inherits the
previous turn's mode.

Tools vocabulary is exactly the composer Tools popover set (spec §3.2):
web_search, deep_crawl, code_execution, browser, image, memory_recall,
artifact_generation. File analysis is an *execution route*, not a tool
toggle: it routes to attached-file context, so it does not invent a
popover toggle that does not exist.

This module never calls a provider, never fabricates citations or
outputs, and never executes code, searches, or agent runs itself — it
returns a routing *decision* that chat_stream_routes.py acts on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

INTENTS = (
    "direct_answer", "teaching", "code_generate", "code_debug",
    "code_refactor", "research", "file_analysis", "artifact_create",
    "diagram", "image", "video", "voice", "agentic_task",
    "clarification", "follow_up", "meta",
)

COMPOSER_MODES = ("auto", "answer", "research", "code", "create", "agent")

TOOL_IDS = (
    "web_search", "deep_crawl", "code_execution", "browser", "image",
    "memory_recall", "artifact_generation",
)

# Intent -> resolved composer mode (Auto only).
_INTENT_MODE = {
    "direct_answer": "answer",
    "teaching": "answer",
    "code_generate": "code",
    "code_debug": "code",
    "code_refactor": "code",
    "research": "research",
    "file_analysis": "answer",
    "artifact_create": "create",
    "diagram": "create",
    "image": "create",
    "video": "answer",  # blocked; mode is moot, kept as answer
    "voice": "answer",
    "agentic_task": "agent",
    "clarification": "answer",
    "follow_up": "answer",  # overridden by inheritance below
    "meta": "answer",
}

# Intent -> execution route (what the chat path should do, beyond tools).
_INTENT_ROUTE = {
    "direct_answer": "direct",
    "teaching": "direct",
    "code_generate": "code",
    "code_debug": "code",
    "code_refactor": "code",
    "research": "search",
    "file_analysis": "file",
    "artifact_create": "artifact",
    "diagram": "artifact",
    "image": "artifact",
    "video": "blocked",
    "voice": "direct",
    "agentic_task": "agent",
    "clarification": "clarification",
    "follow_up": "continuation",
    "meta": "direct",
}

# Intent -> default tools (Auto only; user overrides apply on top).
_INTENT_TOOLS: dict[str, list[str]] = {
    "research": ["web_search"],
    "diagram": ["artifact_generation"],
    "image": ["image"],
    "artifact_create": ["artifact_generation"],
    "code_debug": ["code_execution"],
    "code_generate": [],
    "code_refactor": [],
    "agentic_task": [],
    "file_analysis": [],
    "voice": [],
}

# Time-sensitive signals: the user-approved Auto default — search when the
# query carries a date/news/price/version signal, otherwise answer directly.
_TIME_SIGNALS = (
    "latest", "news", "today", "current", "recent", "this week",
    "this month", "breaking", "price of", "stock price", "exchange rate",
    "version of", "latest version", "newest", "up to date", "up-to-date",
    "who won", "what happened",
)

_FOLLOWUP_PHRASES = (
    "why?", "why", "continue", "go on", "and then?", "and then",
    "fix it", "do that", "explain that", "tell me more", "elaborate",
    "what about that?", "more", "next", "keep going",
)

_EXPERT_TERMS = (
    "idempotency", "idempotent", "ast", "concurrency", "race condition",
    "deadlock", "sharding", "consistency model", "cap theorem",
    "monad", "type inference", "compiler", "kernel", "bytecode",
    "asymptotic", "complexity class", "formal verification",
)

_NOVICE_SIGNALS = (
    "explain like i'm five", "eli5", "beginner", "i'm new to",
    "i am new to", "simple terms", "for a beginner", "dummies",
)


@dataclass
class RouteDecision:
    """One pipeline run, serializable for POST /intelligence/route."""

    intent: str
    mode: str
    tools: list[str] = field(default_factory=list)
    execution_route: str = "direct"
    complexity: float = 0.3
    confidence: float = 0.9
    rule_trace: list[str] = field(default_factory=list)
    classifier_used: bool = False
    classifier: str = "rules"
    needs_search: bool = False
    needs_citations: bool = False
    approval_required: bool = False
    clarification_question: str | None = None
    blocked: bool = False
    blocked_reason: str | None = None
    is_follow_up: bool = False
    continuation_of: str | None = None
    restates_context: bool = False
    depth: str = "auto"  # novice | expert | auto
    post_actions: list[str] = field(default_factory=list)
    next_step: str | None = None
    system_note: str | None = None

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "mode": self.mode,
            "tools": list(self.tools),
            "execution_route": self.execution_route,
            "complexity": self.complexity,
            "confidence": self.confidence,
            "rule_trace": list(self.rule_trace),
            "classifier_used": self.classifier_used,
            "classifier": self.classifier,
            "needs_search": self.needs_search,
            "needs_citations": self.needs_citations,
            "approval_required": self.approval_required,
            "clarification_question": self.clarification_question,
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "is_follow_up": self.is_follow_up,
            "continuation_of": self.continuation_of,
            "restates_context": self.restates_context,
            "depth": self.depth,
            "post_actions": list(self.post_actions),
            "next_step": self.next_step,
            "system_note": self.system_note,
        }


def _has(text: str, *phrases: str) -> bool:
    return any(p in text for p in phrases)


def _word(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def _code_fence(text: str) -> bool:
    return "```" in text


def _score_complexity(text: str, intent: str, history: list[dict]) -> float:
    score = 0.2
    score += min(0.3, len(text) / 1000.0)
    if _code_fence(text):
        score += 0.2
    # Multi-part: several sentences/questions, or a numbered list.
    if len(re.findall(r"[.?]\s+", text)) >= 2 or re.search(r"(?m)^\s*\d+[.)]\s", text):
        score += 0.15
    if intent == "research" and _has(text, "deeply", "deep dive", "in depth", "thorough"):
        score += 0.2
    if intent == "agentic_task":
        score += 0.15
    if history:
        score += 0.05
    return round(min(1.0, score), 2)


def _depth(text: str) -> str:
    if _has(text, *_NOVICE_SIGNALS):
        return "novice"
    if _has(text, *_EXPERT_TERMS):
        return "expert"
    return "auto"


# --- Rule intents: each returns (score, trace) or None -----------------------
# Rules are deliberately near-mutually-exclusive; when two fire with the
# same top score, _small_classifier() breaks the tie (no model involved).

def _rule_follow_up(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if not history:
        return None
    stripped = text.strip().lower().rstrip("?.!")
    if len(text.strip()) <= 40 and stripped in _FOLLOWUP_PHRASES:
        return 1.0, "follow-up phrase with conversation history"
    return None


def _rule_clarification(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    stripped = text.strip().lower()
    if history:
        return None
    if stripped in ("help", "help me", "do something", "it", "that", "this", "huh?", "what?"):
        return 1.0, "vague standalone prompt with no context"
    if len(stripped) < 20 and _word(stripped, "it", "that", "this", "them", "those"):
        return 1.0, "short pronoun-only prompt with no context"
    return None


def _rule_video(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if _has(text, "make a video", "create a video", "generate a video", "video of", "make me a video"):
        return 1.0, "video request (skipped this round)"
    return None


def _rule_diagram(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if _has(text, "make a diagram", "create a diagram", "draw a diagram", "diagram of", "diagram showing", "flowchart", "architecture diagram"):
        return 1.0, "diagram request"
    return None


def _rule_image(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if _has(text, "generate an image", "generate a picture", "create an image", "draw a picture", "draw an image", "make an image"):
        return 1.0, "image generation request"
    return None


def _rule_voice(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if _has(text, "read this aloud", "read aloud", "read out loud", "speak this", "say this aloud", "read this out loud"):
        return 1.0, "voice output request"
    # "read this answer aloud" / "read it aloud": the word carries it.
    if _word(text, "aloud"):
        return 1.0, "voice output request (aloud)"
    return None


def _rule_agentic(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if _has(text, "run this task", "watch for", "remind me", "schedule this", "every morning", "every day", "keep an eye on", "monitor "):
        return 1.0, "agentic/scheduled task request"
    return None


def _rule_refactor(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if _word(text, "refactor") or _has(text, "clean up this code", "rewrite this code"):
        return 1.0, "refactor request"
    return None


def _rule_debug(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    has_code = _code_fence(text) or _has(text, "this code", "my code", "the code above", "traceback", "error:")
    # "doesn't this code work" is not the contiguous phrase "doesn't
    # work", so the contraction + "work" pair counts on its own.
    doesnt_work = bool(re.search(r"doesn.?t\b", text)) and "work" in text
    if has_code and (_has(text, "fix", "debug", "why does this fail", "what's wrong", "what is wrong", "not working", "doesn't work") or doesnt_work):
        return 1.0, "fix/debug request with code context"
    if _code_fence(text) and _has(text, "fix this", "fix it"):
        return 1.0, "fix request with code block"
    return None


def _rule_artifact(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if _has(text, "build me a small app", "build a small app", "build me an app", "build an app",
            "create a landing page", "make a website", "build a website", "make a web page",
            "create a web app", "build a web app", "small app that", "single-page app"):
        return 1.0, "small-app / artifact request"
    return None


def _rule_code_generate(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if _code_fence(text) and _has(text, "write", "generate", "create"):
        return 0.9, "code block plus generation verb"
    if _has(text, "write a function", "write a script", "write a program", "write code",
            "write a python", "write python", "generate code", "implement a function",
            "create a function", "code a ", "write a class"):
        return 1.0, "code generation request"
    return None


def _rule_file_analysis(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if file_ids and _has(text, "summarize", "explain", "what does", "analyse", "analyze", "review", "read"):
        return 1.0, "attached-file request"
    if _has(text, "summarize this file", "summarize this document", "summarize the attached",
            "what does this document say", "explain this file", "analyse this file", "analyze this file"):
        return 1.0, "file/document analysis request"
    return None


def _rule_research(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if _has(text, "research", "deep dive", "search the web", "search for", "look up"):
        return 1.0, "explicit research/search request"
    if _has(text, *_TIME_SIGNALS):
        return 1.0, "date/news/price/version signal (approved Auto default: search)"
    return None


def _rule_teaching(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if _has(text, "explain", "teach me", "how does", "how do i", "how to", "tutorial", "walk me through"):
        return 0.9, "teaching/how-to request"
    return None


def _rule_meta(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if _has(text, "what can you do", "who are you", "what are you", "how do i use sangam", "what is sangam"):
        return 1.0, "meta question about Sangam"
    return None


def _rule_direct(text: str, history: list[dict], file_ids: list[str]) -> tuple[float, str] | None:
    if _has(text, "what is", "what are", "who is", "who was", "when is", "when was",
            "where is", "capital of", "definition of", "meaning of", "population of"):
        return 0.9, "factual question"
    stripped = text.strip()
    if stripped.startswith(("define ", "what ", "who ", "when ", "where ", "which ", "whose ")):
        return 0.8, "factual question shape"
    return None


_RULES: list[tuple[str, object]] = [
    ("follow_up", _rule_follow_up),
    ("clarification", _rule_clarification),
    ("video", _rule_video),
    ("diagram", _rule_diagram),
    ("image", _rule_image),
    ("voice", _rule_voice),
    ("agentic_task", _rule_agentic),
    ("code_refactor", _rule_refactor),
    ("code_debug", _rule_debug),
    ("artifact_create", _rule_artifact),
    ("code_generate", _rule_code_generate),
    ("file_analysis", _rule_file_analysis),
    ("research", _rule_research),
    ("teaching", _rule_teaching),
    ("meta", _rule_meta),
    ("direct_answer", _rule_direct),
]

# Small-classifier keyword weights, used ONLY on a rule tie. Deterministic,
# offline, no model — it is a scorer, and it is labelled as such wherever
# its result is reported.
_CLASSIFIER_WEIGHTS: dict[str, dict[str, int]] = {
    "research": {"research": 3, "news": 2, "latest": 2, "sources": 2, "citations": 2, "deeply": 2},
    "teaching": {"explain": 3, "teach": 3, "tutorial": 2, "how": 1, "understand": 2},
    "code_generate": {"function": 2, "script": 2, "code": 2, "program": 2, "python": 1},
    "direct_answer": {"what": 1, "who": 1, "when": 1, "where": 1, "capital": 2},
    "diagram": {"diagram": 3, "flowchart": 3},
    "artifact_create": {"app": 2, "website": 2, "page": 1, "build": 1},
    "agentic_task": {"watch": 2, "monitor": 2, "remind": 2, "every": 1},
    "file_analysis": {"file": 2, "document": 2, "summarize": 2},
}


def _small_classifier(text: str, tied: list[str]) -> str:
    """Deterministic keyword scorer for rule ties. Never a model call."""
    words = re.findall(r"[a-z]+", text.lower())
    best, best_score = tied[0], -1
    for intent in tied:
        score = sum(w for kw, w in _CLASSIFIER_WEIGHTS.get(intent, {}).items() if kw in words)
        if score > best_score:
            best, best_score = intent, score
    return best


def _last_user_text(history: list[dict]) -> str | None:
    for msg in reversed(history or []):
        if isinstance(msg, dict) and msg.get("role") == "user" and msg.get("content"):
            return str(msg["content"])
    return None


def _inherit_from_history(history: list[dict]) -> tuple[str, str] | None:
    """Route the previous user turn (once, without its own history) so a
    follow-up inherits its intent/mode instead of being re-classified
    from scratch. Returns (intent, mode) or None."""
    prev = _last_user_text(history)
    if not prev:
        return None
    prev_decision = route_message(prev, history=[], file_ids=[])
    if prev_decision.intent in ("follow_up", "clarification"):
        return None
    return prev_decision.intent, prev_decision.mode


def route_message(
    message: str,
    history: list[dict] | None = None,
    file_ids: list[str] | None = None,
    composer_mode: str = "auto",
    tool_overrides: dict[str, bool] | None = None,
    adaptive_depth: bool = True,
) -> RouteDecision:
    """Run the full pipeline for one message. Pure function, no I/O.

    Stages: intake (normalize) -> intent (rules, classifier only on tie)
    -> context assembly (history profile) -> complexity -> capability
    (tools) -> mode selection (Auto-derived or user override) ->
    routing -> validation -> post-response actions.
    """
    history = list(history or [])
    file_ids = list(file_ids or [])
    text = (message or "").strip()
    lower = text.lower()
    mode_requested = (composer_mode or "auto").lower()
    if mode_requested not in COMPOSER_MODES:
        mode_requested = "auto"

    # --- intent detection (rule-first) -------------------------------------
    fired: list[tuple[str, float, str]] = []
    for intent, rule in _RULES:
        hit = rule(lower, history, file_ids)
        if hit:
            score, trace = hit
            fired.append((intent, score, trace))
    if not fired:
        intent, trace, classifier_used = "direct_answer", "default: conversational fallback", False
    else:
        top = max(score for _, score, _ in fired)
        leaders = [(i, t) for i, s, t in fired if s == top]
        if len(leaders) == 1:
            intent, trace, classifier_used = leaders[0][0], leaders[0][1], False
        else:
            intent = _small_classifier(lower, [i for i, _ in leaders])
            trace = "rule tie (" + ", ".join(i for i, _ in leaders) + ") -> keyword scorer"
            classifier_used = True

    # --- context assembly ---------------------------------------------------
    has_code_context = any("```" in str(m.get("content", "")) for m in history)
    inherited = _inherit_from_history(history) if intent == "follow_up" else None

    # --- complexity + depth --------------------------------------------------
    complexity = _score_complexity(lower, intent, history)
    depth = _depth(lower)

    # --- capability selection (Auto tools) -----------------------------------
    tools = list(_INTENT_TOOLS.get(intent, []))
    needs_search = intent == "research"
    needs_citations = intent == "research" or "with sources" in lower or "cite" in lower
    if intent == "research" and _has(lower, "deeply", "deep dive", "in depth", "thorough"):
        if "deep_crawl" not in tools:
            tools.append("deep_crawl")
    if has_code_context and intent in ("code_debug", "code_refactor") and "code_execution" not in tools:
        tools.append("code_execution")

    # --- mode selection -------------------------------------------------------
    if intent == "video":
        mode = "answer"
    elif intent == "follow_up" and inherited:
        mode = inherited[1]
    elif mode_requested != "auto":
        mode = mode_requested
    else:
        mode = _INTENT_MODE[intent]

    # Explicit non-Auto modes narrow tools: Answer only answers directly.
    if mode_requested == "answer":
        tools = []
        needs_search = False
    elif mode_requested == "research":
        needs_search = True
        if "web_search" not in tools:
            tools.append("web_search")
        needs_citations = True
    elif mode_requested == "code" and intent not in ("code_debug", "code_refactor", "code_generate"):
        if "code_execution" not in tools:
            tools.append("code_execution")

    # Per-message tool overrides (composer Tools popover): apply last, and
    # only for this message — the caller never persists them.
    overridden: list[str] = []
    for tool, on in (tool_overrides or {}).items():
        if tool not in TOOL_IDS:
            continue
        if on and tool not in tools:
            tools.append(tool)
            overridden.append(tool)
        elif not on and tool in tools:
            tools.remove(tool)
            overridden.append(tool)
    tools = [t for t in TOOL_IDS if t in tools]
    # An explicit per-message web_search override-off also suppresses the
    # Auto search decision itself (the chat path keys off needs_search),
    # so "off for this message" really means off.
    if (tool_overrides or {}).get("web_search") is False:
        needs_search = False

    # --- routing / validation / completion ------------------------------------
    blocked = intent == "video"
    blocked_reason = (
        "Video production is not available this round. Offer a diagram, "
        "document, or script instead — never invent a video file or link."
        if blocked else None
    )
    clarification_question = None
    if intent == "clarification":
        clarification_question = "What would you like me to help with? Give me a little more detail and I'll take it from there."
    approval_required = intent == "agentic_task"
    execution_route = _INTENT_ROUTE[intent]
    if intent == "follow_up":
        execution_route = "continuation"

    # --- post-response actions -------------------------------------------------
    post_actions = ["save", "view_run"] if mode in ("agent", "code", "create") else ["save"]
    if adaptive_depth:
        post_actions += ["explain_more", "short_version"]
    if needs_citations:
        post_actions.append("view_sources")
    next_step = None
    if intent == "agentic_task":
        next_step = "Approve this task before it runs."
    elif intent == "artifact_create":
        next_step = "Preview the artifact, then ask for changes in one message."
    elif intent == "research":
        next_step = "Ask a follow-up about any source, or say 'continue' for more depth."

    system_note = None
    if blocked:
        system_note = blocked_reason
    elif intent == "clarification":
        system_note = f"Ask exactly one clarification question and stop: {clarification_question} Do not answer yet."
    elif mode_requested == "auto":
        system_note = (
            f"[Auto routing: intent={intent}; mode={mode}; "
            f"tools={','.join(tools) if tools else 'none'}; "
            f"citations_required={str(needs_citations).lower()}]"
        )

    return RouteDecision(
        intent=intent,
        mode=mode,
        tools=tools,
        execution_route=execution_route,
        complexity=complexity,
        confidence=0.95 if not classifier_used else 0.7,
        rule_trace=[trace] + ([f"rule tie -> keyword scorer"] if classifier_used else []),
        classifier_used=classifier_used,
        classifier="keyword-scorer (no model)" if classifier_used else "rules",
        needs_search=needs_search,
        needs_citations=needs_citations,
        approval_required=approval_required,
        clarification_question=clarification_question,
        blocked=blocked,
        blocked_reason=blocked_reason,
        is_follow_up=intent == "follow_up",
        continuation_of=inherited[0] if inherited else None,
        restates_context=False,
        depth=depth,
        post_actions=post_actions,
        next_step=next_step,
        system_note=system_note,
    )
